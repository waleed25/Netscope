'use strict';

/**
 * setup.js — First-run setup logic (runs in the main process)
 *
 * Handles:
 *  - GPU / VRAM detection via nvidia-smi
 *  - Model selection based on available VRAM
 *  - Python embedded runtime bootstrap
 *  - pip + requirements installation
 *  - Ollama installation check / silent install
 *  - Ollama model pull with progress streaming
 *
 * All public functions are async and emit progress via a callback:
 *   onProgress({ stage, message, percent })
 */

const path    = require('path');
const fs      = require('fs');
const os      = require('os');
const { execSync, spawn, spawnSync } = require('child_process');
const https   = require('https');
const http    = require('http');
const AdmZip  = require('adm-zip');   // bundled via npm

// ─── Paths ────────────────────────────────────────────────────────────────────

const IS_PACKAGED = require('electron').app.isPackaged;
const RESOURCES   = IS_PACKAGED
  ? process.resourcesPath
  : path.join(__dirname, '..');

const VENDOR_DIR   = path.join(RESOURCES, 'vendor');
const BACKEND_DIR  = path.join(RESOURCES, 'backend');
const PYEMBED_DIR  = path.join(BACKEND_DIR, '.pyembed');   // embedded Python runtime
const VENV_DIR     = path.join(BACKEND_DIR, '.venv');
const OLLAMA_EXE   = path.join(VENDOR_DIR,  'ollama.exe'); // bundled portable binary

// ─── Model selection table ────────────────────────────────────────────────────

const MODEL_TABLE = [
  // { minVramGB, model, label }
  { minVramGB: 12, model: 'qwen2.5:14b',  label: 'qwen2.5:14b  (14B — high quality, ~9 GB download)' },
  { minVramGB:  6, model: 'qwen3:4b',     label: 'qwen3:4b     (4B  — tool calling, ~2.6 GB download)' },
  { minVramGB:  6, model: 'gemma3:4b',    label: 'gemma3:4b    (4B  — tool calling, ~3.0 GB download)' },
  { minVramGB:  6, model: 'qwen2.5:7b',   label: 'qwen2.5:7b   (7B  — balanced,     ~5 GB download)' },
  { minVramGB:  0, model: 'qwen2.5:3b',   label: 'qwen2.5:3b   (3B  — fast/light,   ~2 GB download)' },
];

/**
 * Detect NVIDIA GPU and VRAM via nvidia-smi.
 * Returns { hasGpu, vramGB, gpuName } — vramGB is 0 if no GPU found.
 */
async function detectGpu() {
  try {
    const raw = execSync(
      'nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits',
      { timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'] }
    ).toString().trim();

    if (!raw) return { hasGpu: false, vramGB: 0, gpuName: null };

    const firstLine = raw.split('\n')[0].trim();
    const parts     = firstLine.split(',').map(s => s.trim());
    const gpuName   = parts[0] || 'Unknown GPU';
    const vramMB    = parseInt(parts[1]) || 0;
    const vramGB    = Math.floor(vramMB / 1024);

    return { hasGpu: true, vramGB, gpuName };
  } catch (_) {
    return { hasGpu: false, vramGB: 0, gpuName: null };
  }
}

/**
 * Pick the best model for the detected VRAM (or CPU fallback).
 */
function pickModel(vramGB) {
  for (const entry of MODEL_TABLE) {
    if (vramGB >= entry.minVramGB) return entry;
  }
  return MODEL_TABLE[MODEL_TABLE.length - 1]; // always falls back to 3b
}

// ─── Ollama ───────────────────────────────────────────────────────────────────

/**
 * Returns the path to the ollama executable to use:
 *   1. System-installed ollama (on PATH)
 *   2. Bundled vendor/ollama.exe
 */
function resolveOllamaExe() {
  try {
    const which = spawnSync('where', ['ollama'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
    if (which.status === 0 && which.stdout.trim()) {
      return which.stdout.trim().split('\n')[0].trim();
    }
  } catch (_) {}
  if (fs.existsSync(OLLAMA_EXE)) return OLLAMA_EXE;
  return null;
}

/**
 * Ensure Ollama is installed.
 * If the bundled ollama.exe exists but is not on PATH, we copy it to a
 * writable location in %LOCALAPPDATA%\NetScope and add it to the session PATH.
 */
async function ensureOllama(onProgress) {
  onProgress({ stage: 'ollama', message: 'Checking for Ollama…', percent: 0 });

  let ollamaExe = resolveOllamaExe();

  if (!ollamaExe) {
    onProgress({ stage: 'ollama', message: 'Ollama not found — copying bundled binary…', percent: 10 });
    // Should not happen if fetch_vendors.ps1 was run, but handle gracefully
    throw new Error('Ollama binary not found. Please run scripts/fetch_vendors.ps1 before building.');
  }

  // Copy to a user-writable location so it can be spawned reliably
  const localBin = path.join(os.homedir(), 'AppData', 'Local', 'NetScope', 'bin');
  fs.mkdirSync(localBin, { recursive: true });
  const localOllama = path.join(localBin, 'ollama.exe');

  if (!fs.existsSync(localOllama)) {
    onProgress({ stage: 'ollama', message: 'Installing Ollama…', percent: 20 });
    fs.copyFileSync(ollamaExe, localOllama);
  }

  // Add to PATH for this process
  process.env.PATH = `${localBin};${process.env.PATH}`;

  onProgress({ stage: 'ollama', message: 'Ollama ready.', percent: 100 });
  return localOllama;
}

/**
 * Start the Ollama server as a background process.
 * Returns the child process handle.
 */
function startOllamaServer(ollamaExe) {
  const ollamaData = path.join(os.homedir(), 'AppData', 'Local', 'NetScope', 'ollama');
  fs.mkdirSync(ollamaData, { recursive: true });

  const proc = spawn(ollamaExe, ['serve'], {
    env: Object.assign({}, process.env, {
      OLLAMA_MODELS: ollamaData,
      OLLAMA_HOST:   '127.0.0.1:11434',
    }),
    detached:    false,
    windowsHide: true,
    stdio:       'ignore',
  });

  return proc;
}

/**
 * Wait for the Ollama server to respond on /api/tags.
 */
function waitForOllamaServer(maxWaitMs = 30_000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + maxWaitMs;
    function check() {
      if (Date.now() > deadline) return reject(new Error('Ollama server did not start in time.'));
      const req = http.get('http://127.0.0.1:11434/api/tags', (res) => {
        if (res.statusCode === 200) return resolve();
        setTimeout(check, 600);
      });
      req.on('error', () => setTimeout(check, 600));
      req.setTimeout(600, () => { req.destroy(); setTimeout(check, 600); });
    }
    check();
  });
}

/**
 * Check whether a model is already pulled.
 */
async function isModelPulled(modelName) {
  return new Promise((resolve) => {
    const req = http.get('http://127.0.0.1:11434/api/tags', (res) => {
      let body = '';
      res.on('data', d => body += d);
      res.on('end', () => {
        try {
          const data = JSON.parse(body);
          const models = (data.models || []).map(m => m.name);
          resolve(models.some(n => n === modelName || n.startsWith(modelName.split(':')[0])));
        } catch (_) { resolve(false); }
      });
    });
    req.on('error', () => resolve(false));
  });
}

/**
 * Pull a model from Ollama with streaming progress.
 * onProgress is called with { stage, message, percent }.
 */
async function pullModel(ollamaExe, modelName, onProgress) {
  return new Promise((resolve, reject) => {
    onProgress({ stage: 'model', message: `Starting pull of ${modelName}…`, percent: 0 });

    const proc = spawn(ollamaExe, ['pull', modelName], {
      env: Object.assign({}, process.env, { OLLAMA_HOST: '127.0.0.1:11434' }),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });

    let lastPercent = 0;

    proc.stdout.on('data', (chunk) => {
      const text = chunk.toString();
      // Ollama outputs lines like: "pulling sha256:abc... 45%"
      const match = text.match(/(\d+)%/);
      if (match) {
        lastPercent = parseInt(match[1]);
        onProgress({ stage: 'model', message: `Downloading ${modelName}: ${lastPercent}%`, percent: lastPercent });
      } else if (text.trim()) {
        onProgress({ stage: 'model', message: text.trim().slice(0, 80), percent: lastPercent });
      }
    });

    proc.stderr.on('data', (chunk) => {
      const text = chunk.toString().trim();
      if (text) onProgress({ stage: 'model', message: text.slice(0, 80), percent: lastPercent });
    });

    proc.on('exit', (code) => {
      if (code === 0) {
        onProgress({ stage: 'model', message: `${modelName} ready.`, percent: 100 });
        resolve();
      } else {
        reject(new Error(`ollama pull exited with code ${code}`));
      }
    });
  });
}

// ─── Download helper ──────────────────────────────────────────────────────────

/**
 * Download a URL to a local file path, resolving when complete.
 */
function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    const tmp = dest + '.tmp';
    const file = fs.createWriteStream(tmp);

    function get(targetUrl) {
      const mod = targetUrl.startsWith('https') ? https : http;
      mod.get(targetUrl, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          file.close();
          return get(res.headers.location);
        }
        if (res.statusCode !== 200) {
          file.close();
          fs.unlink(tmp, () => {});
          return reject(new Error(`Download failed: HTTP ${res.statusCode} for ${targetUrl}`));
        }
        res.pipe(file);
        file.on('finish', () => {
          file.close(() => {
            fs.renameSync(tmp, dest);
            resolve();
          });
        });
      }).on('error', (err) => {
        file.close();
        fs.unlink(tmp, () => {});
        reject(err);
      });
    }
    get(url);
  });
}

// ─── Python bootstrap ─────────────────────────────────────────────────────────

const PYTHON_VERSION = '3.11.9';

/**
 * Bootstrap the embedded Python runtime from the bundled zip.
 * If the zip is missing (e.g. dev mode), it is downloaded automatically.
 * Uses the Python embeddable package — no system Python required.
 */
async function bootstrapPython(onProgress) {
  const pyZip    = path.join(VENDOR_DIR, 'python-embed.zip');
  const getPip   = path.join(VENDOR_DIR, 'get-pip.py');
  const pyExe    = path.join(PYEMBED_DIR, 'python.exe');
  const pipExe   = path.join(PYEMBED_DIR, 'Scripts', 'pip.exe');

  if (fs.existsSync(pyExe) && fs.existsSync(pipExe)) {
    onProgress({ stage: 'python', message: 'Python runtime already set up.', percent: 100 });
    return pyExe;
  }

  // Download embed zip if missing (dev mode or missing vendor step)
  if (!fs.existsSync(pyZip)) {
    onProgress({ stage: 'python', message: 'Downloading Python embeddable runtime…', percent: 5 });
    const pyUrl = `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip`;
    await downloadFile(pyUrl, pyZip);
  }

  onProgress({ stage: 'python', message: 'Extracting Python runtime…', percent: 10 });
  fs.mkdirSync(PYEMBED_DIR, { recursive: true });

  const zip = new AdmZip(pyZip);
  zip.extractAllTo(PYEMBED_DIR, true);

  // The embeddable zip disables site-packages by default; enable it by editing
  // the python311._pth file.
  const pthFiles = fs.readdirSync(PYEMBED_DIR).filter(f => f.endsWith('._pth'));
  for (const pthFile of pthFiles) {
    const pthPath = path.join(PYEMBED_DIR, pthFile);
    let content = fs.readFileSync(pthPath, 'utf8');
    // Uncomment the `import site` line
    content = content.replace('#import site', 'import site');
    // Add Lib/site-packages to path
    content += '\nLib\\site-packages\n';
    fs.writeFileSync(pthPath, content, 'utf8');
  }

  // Download get-pip.py if missing
  onProgress({ stage: 'python', message: 'Installing pip…', percent: 40 });
  if (!fs.existsSync(getPip)) {
    onProgress({ stage: 'python', message: 'Downloading pip bootstrap…', percent: 35 });
    await downloadFile('https://bootstrap.pypa.io/get-pip.py', getPip);
  }
  spawnSync(pyExe, [getPip, '--no-warn-script-location', '-q'], {
    cwd: PYEMBED_DIR,
    stdio: 'inherit',
  });

  onProgress({ stage: 'python', message: 'pip installed.', percent: 100 });
  return pyExe;
}

/**
 * Install backend Python requirements into the embedded runtime.
 */
async function installRequirements(pyExe, onProgress) {
  const reqFile   = path.join(BACKEND_DIR, 'requirements.txt');
  const pipExe    = path.join(PYEMBED_DIR, 'Scripts', 'pip.exe');
  const stampFile = path.join(PYEMBED_DIR, '.requirements_installed');

  // Check if already installed (use a stamp file)
  if (fs.existsSync(stampFile)) {
    const stamp = fs.readFileSync(stampFile, 'utf8').trim();
    const reqHash = require('crypto')
      .createHash('md5')
      .update(fs.readFileSync(reqFile))
      .digest('hex');
    if (stamp === reqHash) {
      onProgress({ stage: 'pip', message: 'Python packages already installed.', percent: 100 });
      return;
    }
  }

  onProgress({ stage: 'pip', message: 'Installing Python packages (CPU PyTorch)…', percent: 5 });

  // Install CPU torch first (much smaller than CUDA variant; GPU inference goes
  // through Ollama, not torch directly)
  spawnSync(pipExe, [
    'install', 'torch', 'torchvision', 'torchaudio',
    '--index-url', 'https://download.pytorch.org/whl/cpu',
    '--quiet',
  ], { stdio: 'inherit' });

  onProgress({ stage: 'pip', message: 'Installing remaining requirements…', percent: 40 });

  spawnSync(pipExe, [
    'install', '-r', reqFile,
    '--quiet',
    '--no-warn-script-location',
  ], { stdio: 'inherit', cwd: BACKEND_DIR });

  // Write stamp
  const reqHash = require('crypto')
    .createHash('md5')
    .update(fs.readFileSync(reqFile))
    .digest('hex');
  fs.writeFileSync(stampFile, reqHash, 'utf8');

  onProgress({ stage: 'pip', message: 'All packages installed.', percent: 100 });
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Returns true if this is a first run (no stamp file present).
 */
function isFirstRun() {
  return !fs.existsSync(path.join(PYEMBED_DIR, '.requirements_installed'));
}

/**
 * Full setup sequence.  Calls onProgress({ stage, message, percent }) throughout.
 * Returns { ollamaExe, ollamaProc, modelName, pyExe } on success.
 */
async function runSetup(onProgress) {
  // 1. GPU detection
  onProgress({ stage: 'gpu', message: 'Detecting GPU…', percent: 0 });
  const gpu = await detectGpu();
  const modelEntry = pickModel(gpu.vramGB);

  if (gpu.hasGpu) {
    onProgress({
      stage: 'gpu',
      message: `Found ${gpu.gpuName} (${gpu.vramGB} GB VRAM) → using ${modelEntry.model}`,
      percent: 100,
    });
  } else {
    onProgress({
      stage: 'gpu',
      message: `No NVIDIA GPU detected → using CPU model ${modelEntry.model}`,
      percent: 100,
    });
  }

  // 2. Python bootstrap
  const pyExe = await bootstrapPython(onProgress);

  // 3. Python requirements
  await installRequirements(pyExe, onProgress);

  // 4. Ollama
  const ollamaExe = await ensureOllama(onProgress);

  // 5. Start Ollama server
  onProgress({ stage: 'ollama', message: 'Starting Ollama server…', percent: 10 });
  const ollamaProc = startOllamaServer(ollamaExe);
  await waitForOllamaServer();
  onProgress({ stage: 'ollama', message: 'Ollama server running.', percent: 100 });

  // 6. Pull model if needed
  const alreadyPulled = await isModelPulled(modelEntry.model);
  if (!alreadyPulled) {
    await pullModel(ollamaExe, modelEntry.model, onProgress);
  } else {
    onProgress({ stage: 'model', message: `${modelEntry.model} already downloaded.`, percent: 100 });
  }

  // 7. Write .env for the backend so it uses the right model
  const envPath = path.join(BACKEND_DIR, '.env');
  const envContent = [
    `LLM_BACKEND=ollama`,
    `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1`,
    `OLLAMA_MODEL=${modelEntry.model}`,
  ].join('\n') + '\n';
  fs.writeFileSync(envPath, envContent, 'utf8');

  onProgress({ stage: 'done', message: 'Setup complete. Launching NetScope…', percent: 100 });

  return { ollamaExe, ollamaProc, modelName: modelEntry.model, pyExe, gpu };
}

module.exports = {
  isFirstRun,
  runSetup,
  detectGpu,
  pickModel,
  startOllamaServer,
  waitForOllamaServer,
  resolveOllamaExe,
  MODEL_TABLE,
  PYEMBED_DIR,
  OLLAMA_EXE,
};
