'use strict';

/**
 * Electron main process — NetScope (3-process architecture)
 *
 * Flow:
 *  1. First run  → open the setup wizard window
 *                  wizard runs GPU detection, Python bootstrap, Ollama install, model pull
 *                  on completion → close wizard, continue to step 2
 *  2. Normal run → start Ollama server (if not already running)
 *                  start Redis (if not already running)
 *                  start Capture Daemon (elevated — raw packet capture + Modbus)
 *                  start AI Engine (user-level — LLM + RAG + agent tools)
 *                  start Gateway (user-level — HTTP/WS API proxy)
 *                  wait for Gateway /health
 *                  open the main BrowserWindow
 */

const { app, BrowserWindow, ipcMain, dialog, shell, session } = require('electron');
const path   = require('path');
const fs     = require('fs');
const os     = require('os');
const http   = require('http');
const { spawn, execSync } = require('child_process');

// ─── Paths ────────────────────────────────────────────────────────────────────

const IS_PACKAGED = app.isPackaged;

// ─── installed.json helpers ──────────────────────────────────────────────────

const DATA_DIR = path.join(app.getPath('userData'), 'netscope');

function readInstalled() {
  const p = path.join(DATA_DIR, 'installed.json');
  try {
    if (!fs.existsSync(p)) return null;  // first run
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch (e) {
    console.error('[main] Failed to read installed.json:', e.message);
    return null;
  }
}

function isModuleEnabled(installed, moduleName) {
  if (!installed) return true;  // first run: all enabled
  return installed?.modules?.[moduleName]?.enabled ?? true;
}

const RESOURCES    = IS_PACKAGED
  ? process.resourcesPath
  : path.join(__dirname, '..');

const BACKEND_DIR  = path.join(RESOURCES, 'backend');
const FRONTEND_DIR = path.join(RESOURCES, 'frontend', 'dist');
const VENDOR_DIR   = path.join(RESOURCES, 'vendor');
const PYEMBED_DIR  = path.join(BACKEND_DIR, '.pyembed');
const VENV_DIR     = path.join(BACKEND_DIR, '.venv');

// New process directories
const GATEWAY_DIR  = path.join(RESOURCES, 'gateway');
const DAEMON_DIR   = path.join(RESOURCES, 'daemon');
const ENGINE_DIR   = path.join(RESOURCES, 'engine');

// ─── Setup module (lazy — only needed after app ready) ────────────────────────
let setup = null;
function getSetup() {
  if (!setup) setup = require('./setup');
  return setup;
}

// ─── Port selection ───────────────────────────────────────────────────────────
let backendPort = 8000;

function isPortFree(port) {
  return new Promise((resolve) => {
    const server = require('net').createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => { server.close(); resolve(true); });
    server.listen(port, '127.0.0.1');
  });
}

async function pickPort(start = 8000) {
  for (let p = start; p < start + 20; p++) {
    if (await isPortFree(p)) return p;
  }
  return start;
}

// ─── Process handles ─────────────────────────────────────────────────────────
let backendProcess  = null;  // legacy fallback (single-process mode)
let ollamaProcess   = null;
let gatewayProcess  = null;
let daemonProcess   = null;
let engineProcess   = null;
let redisProcess    = null;

// Architecture mode: 'multi' (3-process) or 'legacy' (single backend)
// Auto-detect: use multi-process if gateway/main.py exists
let archMode = 'legacy';

// ─── Python exe resolution ────────────────────────────────────────────────────
function resolvePython() {
  // 1. Embedded runtime (bootstrapped by setup wizard)
  const embedPy = path.join(PYEMBED_DIR, 'python.exe');
  if (fs.existsSync(embedPy)) return embedPy;

  // 2. Traditional venv (developer workflow)
  const venvPy = path.join(VENV_DIR, 'Scripts', 'python.exe');
  if (fs.existsSync(venvPy)) return venvPy;

  // 3. Fallback: system Python
  if (process.platform === 'win32') {
    // Avoid Windows Store alias trap by finding the actual python.exe
    let absolutePython = 'python';
    try {
      const { execSync } = require('child_process');
      const out = execSync('powershell -NoProfile -Command "Get-Command python | Select-Object -ExpandProperty Path"').toString().trim();
      if (fs.existsSync(out)) absolutePython = out;
    } catch (_) {}
    return absolutePython;
  }
  return 'python3';
}

// ─── Backend ──────────────────────────────────────────────────────────────────
async function startBackend() {
  backendPort = await pickPort(8000);
  const python = resolvePython();

  const env = Object.assign({}, process.env, {
    PORT:             String(backendPort),
    HOST:             '127.0.0.1',
    CORS_ORIGINS:     JSON.stringify([`http://localhost:${backendPort}`, `http://127.0.0.1:${backendPort}`]),
    RAG_DATA_DIR:     path.join(app.getPath('userData'), 'data'),
    PYTHONUNBUFFERED: '1',
    // Tell the backend where the embedded site-packages are
    PYTHONPATH:       path.join(PYEMBED_DIR, 'Lib', 'site-packages'),
  });

  console.log(`[main] Starting backend on port ${backendPort} with ${python}`);

  backendProcess = spawn(
    python,
    ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(backendPort)],
    { cwd: BACKEND_DIR, env, windowsHide: true }
  );

  backendProcess.stdout.on('data', d => process.stdout.write(`[backend] ${d}`));
  backendProcess.stderr.on('data', d => process.stderr.write(`[backend] ${d}`));
  backendProcess.on('exit', code => {
    console.log(`[main] Backend exited (${code})`);
    backendProcess = null;
  });
}

function stopBackend() {
  if (!backendProcess) return;
  _killProcess(backendProcess, 'backend');
  backendProcess = null;
}

function stopOllama() {
  if (!ollamaProcess) return;
  _killProcess(ollamaProcess, 'ollama');
  ollamaProcess = null;
}

// ─── Process kill helper ──────────────────────────────────────────────────────
function _killProcess(proc, label) {
  if (!proc) return;
  try {
    if (process.platform === 'win32') {
      execSync(`taskkill /PID ${proc.pid} /T /F`, { stdio: 'ignore' });
    } else {
      process.kill(-proc.pid, 'SIGTERM');
    }
    console.log(`[main] Stopped ${label} (PID ${proc.pid})`);
  } catch (_) {
    try { proc.kill(); } catch (_) {}
  }
}

// ─── Redis startup ────────────────────────────────────────────────────────────
async function startRedis() {
  // Check if Redis is already running on port 6379
  const already = await new Promise(resolve => {
    const net = require('net');
    const client = new net.Socket();
    client.connect(6379, '127.0.0.1', () => { client.destroy(); resolve(true); });
    client.on('error', () => resolve(false));
    client.setTimeout(1500, () => { client.destroy(); resolve(false); });
  });

  if (already) {
    console.log('[main] Redis already running on port 6379.');
    return;
  }

  // Try to find a bundled Redis (Memurai on Windows)
  const redisPaths = [
    path.join(VENDOR_DIR, 'memurai', 'memurai-cli.exe'),
    path.join(VENDOR_DIR, 'redis', 'redis-server.exe'),
    // System-installed fallbacks
    'redis-server',
    'memurai-cli',
  ];

  let redisExe = null;
  for (const p of redisPaths) {
    if (p.includes(path.sep) && !fs.existsSync(p)) continue;
    redisExe = p;
    break;
  }

  if (!redisExe) {
    console.warn('[main] No Redis binary found — will try system PATH…');
    redisExe = 'redis-server';  // last resort
  }
  global._redisExe = redisExe;

  const debugLog = path.join(app.getPath('userData'), 'electron_flow.log');
  fs.appendFileSync(debugLog, `\n[main] Starting Redis: ${redisExe}\n`);

  try {
    redisProcess = spawn(redisExe, [], {
      cwd: app.getPath('userData'),
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    redisProcess.stdout.on('data', d => process.stdout.write(`[redis] ${d}`));
    redisProcess.stderr.on('data', d => process.stderr.write(`[redis] ${d}`));
    redisProcess.on('exit', code => {
      console.log(`[main] Redis exited (${code})`);
      redisProcess = null;
    });

    // Wait for Redis to become responsive
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline) {
      const ok = await new Promise(resolve => {
        const net = require('net');
        const c = new net.Socket();
        c.connect(6379, '127.0.0.1', () => { c.destroy(); resolve(true); });
        c.on('error', () => resolve(false));
        c.setTimeout(500, () => { c.destroy(); resolve(false); });
      });
      if (ok) {
        console.log('[main] Redis ready on port 6379.');
        return;
      }
      await new Promise(r => setTimeout(r, 300));
    }
    console.warn('[main] Redis did not become responsive in 10s — continuing anyway.');
  } catch (err) {
    console.warn(`[main] Could not start Redis: ${err.message} — continuing without it.`);
  }
}

function stopRedis() {
  _killProcess(redisProcess, 'redis');
  redisProcess = null;
}

// ─── Multi-process: Gateway, Daemon, Engine ──────────────────────────────────

function _buildPythonEnv(extraVars = {}) {
  return Object.assign({}, process.env, {
    PYTHONUNBUFFERED: '1',
    PYTHONPATH: [
      path.join(PYEMBED_DIR, 'Lib', 'site-packages'),
      RESOURCES,       // so `shared.*` is importable
      BACKEND_DIR,     // so transitional imports still work (config, utils, etc.)
    ].join(path.delimiter),
    RAG_DATA_DIR: path.join(app.getPath('userData'), 'data'),
    ...extraVars,
  });
}

async function startGateway() {
  backendPort = await pickPort(8000);
  const python = resolvePython();
  const gatewayMain = path.join(GATEWAY_DIR, 'main.py');

  const env = _buildPythonEnv({
    PORT: String(backendPort),
    HOST: '127.0.0.1',
    CORS_ORIGINS: JSON.stringify([`http://localhost:${backendPort}`, `http://127.0.0.1:${backendPort}`]),
  });

  const debugLog = path.join(app.getPath('userData'), 'electron_flow.log');
  fs.appendFileSync(debugLog, `\n[main] Starting Gateway on port ${backendPort} with python: ${python}\n`);
  
  try {
    gatewayProcess = spawn(
      python,
      ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(backendPort)],
      { cwd: GATEWAY_DIR, env, windowsHide: true, shell: process.platform === 'win32' }
    );
    fs.appendFileSync(debugLog, `[main] Gateway spawned (PID: ${gatewayProcess.pid})\n`);
    if (gatewayProcess) {
      gatewayProcess.stdout?.on('data', d => {
        process.stdout.write(`[gateway] ${d}`);
        fs.appendFileSync(path.join(app.getPath('userData'), 'gateway.log'), `[OUT] ${d}`);
      });
      gatewayProcess.stderr?.on('data', d => {
        process.stderr.write(`[gateway] ${d}`);
        fs.appendFileSync(path.join(app.getPath('userData'), 'gateway.log'), `[ERR] ${d}`);
      });
      gatewayProcess.on('exit', code => {
        console.log(`[main] Gateway exited (${code})`);
        gatewayProcess = null;
      });
    }
  } catch (err) {
    fs.appendFileSync(debugLog, `[main] Gateway spawn error: ${err.message}\n`);
  }
}

async function startDaemon() {
  const python = resolvePython();
  const daemonMain = path.join(DAEMON_DIR, 'main.py');

  const env = _buildPythonEnv();

  console.log('[main] Starting Capture Daemon (elevated)…');
  
  if (IS_PACKAGED && process.platform === 'win32') {
    // In production, spawn with UAC elevation via PowerShell
    const psArgs = `-WindowStyle Hidden -FilePath "${python}" -ArgumentList '"${daemonMain}"' -Verb RunAs`;
    daemonProcess = spawn('powershell.exe', ['-NoProfile', '-WindowStyle', 'Hidden', '-Command', `Start-Process ${psArgs}`], {
      cwd: DAEMON_DIR, env, windowsHide: true
    });
    // The powershell process exits quickly; the elevated Python runs detached.
    // It will be shut down gracefully by the stopAllProcesses() Redis signal.
  } else {
    // For development, spawn normally (assumes you ran Electron/ VS Code as Admin)
    daemonProcess = spawn(
      python,
      [daemonMain],
      { cwd: DAEMON_DIR, env, windowsHide: true, shell: process.platform === 'win32' }
    );
    daemonProcess.stdout.on('data', d => process.stdout.write(`[daemon] ${d}`));
    daemonProcess.stderr.on('data', d => process.stderr.write(`[daemon] ${d}`));
    daemonProcess.on('exit', code => {
      console.log(`[main] Daemon exited (${code})`);
      daemonProcess = null;
    });
  }
}

async function startEngine() {
  const python = resolvePython();
  const engineMain = path.join(ENGINE_DIR, 'main.py');

  const env = _buildPythonEnv();

  console.log('[main] Starting AI Engine…');
  try {
    engineProcess = spawn(
      python,
      [engineMain],
      { cwd: ENGINE_DIR, env, windowsHide: true, shell: process.platform === 'win32' }
    );
    if (engineProcess) {
      engineProcess.stdout?.on('data', d => process.stdout.write(`[engine] ${d}`));
      engineProcess.stderr?.on('data', d => process.stderr.write(`[engine] ${d}`));
      engineProcess.on('exit', code => {
        console.log(`[main] Engine exited (${code})`);
        engineProcess = null;
      });
    }
  } catch (err) {
    console.warn(`[main] Engine spawn error: ${err.message}`);
  }
}

function stopAllProcesses() {
  if (redisProcess || !IS_PACKAGED) {
    try {
      const { execSync } = require('child_process');
      // If we found a bundled redisExe, the CLI is usually in the same folder.
      let cliPath = 'redis-cli';
      if (global._redisExe) {
        cliPath = global._redisExe.replace('redis-server', 'redis-cli').replace('memurai.exe', 'memurai-cli.exe');
      }
      execSync(`"${cliPath}" -p 6379 PUBLISH ns:daemon.shutdown 1`, { stdio: 'ignore' });
    } catch (_) { }
  }

  _killProcess(gatewayProcess, 'gateway');
  gatewayProcess = null;
  _killProcess(daemonProcess, 'daemon');
  daemonProcess = null;
  _killProcess(engineProcess, 'engine');
  engineProcess = null;
  _killProcess(backendProcess, 'backend');
  backendProcess = null;
  stopRedis();
  _killProcess(ollamaProcess, 'ollama');
  ollamaProcess = null;
}

// ─── Health check ─────────────────────────────────────────────────────────────
function waitForBackend(port, maxWaitMs = 60_000, intervalMs = 500) {
  const debugLog = path.join(app.getPath('userData'), 'electron_flow.log');
  fs.appendFileSync(debugLog, `[main] Waiting for backend at http://127.0.0.1:${port}/health\n`);
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + maxWaitMs;
    function check() {
      if (Date.now() > deadline) {
        fs.appendFileSync(debugLog, `[main] Backend timeout\n`);
        return reject(new Error(`Backend did not start within ${maxWaitMs / 1000}s`));
      }
      const req = http.get(`http://127.0.0.1:${port}/health`, res => {
        if (res.statusCode === 200) {
          fs.appendFileSync(debugLog, `[main] Backend is ready!\n`);
          return resolve();
        }
        setTimeout(check, intervalMs);
      });
      req.on('error', () => setTimeout(check, intervalMs));
      req.setTimeout(intervalMs, () => { req.destroy(); setTimeout(check, intervalMs); });
    }
    check();
  });
}

// ─── Main window ──────────────────────────────────────────────────────────────
let mainWindow = null;

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width:  1440,
    height: 900,
    minWidth:  1024,
    minHeight: 640,
    title: 'NetScope',
    backgroundColor: '#0d1117',
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
      webSecurity:      IS_PACKAGED,
    },
    autoHideMenuBar: true,
  });

  const indexHtml = path.join(FRONTEND_DIR, 'index.html');
  if (IS_PACKAGED || fs.existsSync(indexHtml)) {
    mainWindow.loadFile(indexHtml);
  } else {
    mainWindow.loadURL('http://localhost:4173');
    mainWindow.webContents.openDevTools();
  }

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const parsed = new URL(url);
      if (['http:', 'https:'].includes(parsed.protocol)) {
        shell.openExternal(url);
      }
    } catch (_) {}
    return { action: 'deny' };
  });

  // Set Content-Security-Policy now that backendPort is known
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          `default-src 'self'; ` +
          `script-src 'self'; ` +
          `style-src 'self' 'unsafe-inline'; ` +
          `connect-src http://127.0.0.1 ws://127.0.0.1 https://api.github.com; ` +
          `img-src 'self' data:; ` +
          `font-src 'self' data:;`
        ],
      },
    });
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ─── Setup wizard window ──────────────────────────────────────────────────────
let wizardWindow = null;

function createWizardWindow() {
  wizardWindow = new BrowserWindow({
    width:  580,
    height: 620,
    resizable:  false,
    frame:      false,
    title: 'NetScope — Setup',
    backgroundColor: '#0d1117',
    webPreferences: {
      preload:          path.join(__dirname, 'wizard', 'wizard-preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
    },
  });

  wizardWindow.loadFile(path.join(__dirname, 'wizard', 'wizard.html'));
  wizardWindow.on('closed', () => { wizardWindow = null; });
}

// ─── IPC handlers for the wizard ─────────────────────────────────────────────

ipcMain.handle('wizard:detectGpu', async () => {
  return getSetup().detectGpu();
});

ipcMain.handle('wizard:pickModel', async (_event, vramGB) => {
  const gb = Number(vramGB);
  if (!Number.isFinite(gb) || gb < 0 || gb > 256) {
    throw new Error(`Invalid vramGB value: ${vramGB}`);
  }
  return getSetup().pickModel(gb);
});

ipcMain.handle('wizard:runSetup', async (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);

  const onProgress = (data) => {
    if (win && !win.isDestroyed()) {
      win.webContents.send('wizard:progress', data);
    }
  };

  const result = await getSetup().runSetup(onProgress);

  // Keep the Ollama process handle so we can shut it down with the app
  ollamaProcess = result.ollamaProc;

  return {
    modelName: result.modelName,
    gpu:       result.gpu,
    ollamaExe: result.ollamaExe,
  };
});

// ─── IPC: synchronous backend port getter ────────────────────────────────────
// Preload reads this synchronously so the React app has the port before mount.
ipcMain.on('get-backend-port', (event) => {
  event.returnValue = backendPort;
});

// ─── IPC: open external URL (http/https only) ────────────────────────────────
ipcMain.handle('open-external', async (_event, url) => {
  try {
    const parsed = new URL(url);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      throw new Error(`Blocked non-http(s) scheme: ${parsed.protocol}`);
    }
    return shell.openExternal(url);
  } catch (err) {
    console.warn('[main] open-external blocked:', err.message);
    throw err;
  }
});

// ─── IPC: restart backend ─────────────────────────────────────────────────────
ipcMain.handle('restart-backend', async () => {
  console.log(`[main] Restarting backend (${archMode} mode)…`);

  if (archMode === 'multi') {
    // Stop worker processes (keep Redis running)
    _killProcess(gatewayProcess, 'gateway');  gatewayProcess = null;
    _killProcess(daemonProcess, 'daemon');    daemonProcess  = null;
    _killProcess(engineProcess, 'engine');    engineProcess  = null;
    await new Promise(r => setTimeout(r, 500));
    await startDaemon();
    await new Promise(r => setTimeout(r, 1500));
    await startEngine();
    await new Promise(r => setTimeout(r, 1000));
    await startGateway();
  } else {
    stopBackend();
    await new Promise(r => setTimeout(r, 800));
    await startBackend();
  }

  await waitForBackend(backendPort);
  console.log(`[main] Backend restarted on port ${backendPort}`);
  return { port: backendPort };
});

ipcMain.on('wizard:finish', async (_event, data) => {
  // Write installed.json — use selectedModules from wizard if provided
  try {
    const ALL_MODULES = ['capture', 'modbus', 'llm-agent', 'rag', 'expert-analysis',
                         'ics-dnp3', 'topology', 'scheduler', 'exec', 'channels'];
    const selectedModules = (data && Array.isArray(data.selectedModules) && data.selectedModules.length > 0)
      ? data.selectedModules
      : ALL_MODULES;
    const installedData = {
      installed_at: new Date().toISOString(),
      modules: {}
    };
    ALL_MODULES.forEach(name => {
      installedData.modules[name] = { enabled: selectedModules.includes(name), version: '1.0.0' };
    });
    fs.mkdirSync(DATA_DIR, { recursive: true });
    fs.writeFileSync(
      path.join(DATA_DIR, 'installed.json'),
      JSON.stringify(installedData, null, 2)
    );
    console.log('[main] Wrote installed.json to', DATA_DIR);
  } catch (e) {
    console.error('[main] Failed to write installed.json:', e.message);
  }

  if (wizardWindow && !wizardWindow.isDestroyed()) {
    wizardWindow.close();
  }
  await launchApp();
});

// ─── Capability detection for wizard ─────────────────────────────────────────
ipcMain.handle('wizard:detectCapabilities', async () => {
  return new Promise((resolve) => {
    const detectorPath = path.join(__dirname, 'capability_detector.py');
    const { spawnSync } = require('child_process');
    const pythonExe = resolvePython();
    const result = spawnSync(pythonExe, [detectorPath], {
      encoding: 'utf8',
      timeout: 10000,
    });
    try {
      resolve(JSON.parse(result.stdout || '{}'));
    } catch {
      resolve({ error: result.stderr || 'Detection failed' });
    }
  });
});

// ─── Get available modules from manifests ────────────────────────────────────
ipcMain.handle('wizard:getModules', async () => {
  const modulesDir = path.join(__dirname, '..', 'modules');
  const modules = [];
  try {
    const { readdirSync, readFileSync, existsSync } = require('fs');
    if (!existsSync(modulesDir)) return [];
    for (const name of readdirSync(modulesDir)) {
      const manifestPath = path.join(modulesDir, name, 'manifest.toml');
      if (!existsSync(manifestPath)) continue;
      // Parse basic TOML fields manually (avoid deps)
      const content = readFileSync(manifestPath, 'utf8');
      const getName = (c) => { const m = c.match(/^name\s*=\s*"([^"]+)"/m); return m ? m[1] : name; };
      const getField = (c, field) => { const m = c.match(new RegExp(`^${field}\\s*=\\s*"([^"]+)"`, 'm')); return m ? m[1] : ''; };
      const getBool = (c, field) => { const m = c.match(new RegExp(`^${field}\\s*=\\s*(true|false)`, 'm')); return m ? m[1] === 'true' : false; };
      const getFloat = (c, field) => { const m = c.match(new RegExp(`^${field}\\s*=\\s*([\\d.]+)`, 'm')); return m ? parseFloat(m[1]) : 0; };
      modules.push({
        name: getName(content),
        description: getField(content, 'description'),
        optional: getBool(content, 'optional'),
        needs_npcap: getBool(content, 'needs_npcap') || content.includes('needs_npcap = true'),
        ram_gb_min: getFloat(content, 'ram_gb_min'),
      });
    }
  } catch (e) {
    console.error('[wizard:getModules]', e);
  }
  return modules;
});

// ─── Ollama startup (normal / repeat runs) ────────────────────────────────────
async function ensureOllamaRunning() {
  const s = getSetup();

  // Check if already running
  const already = await new Promise(resolve => {
    const req = http.get('http://127.0.0.1:11434/api/tags', res => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.setTimeout(1000, () => { req.destroy(); resolve(false); });
  });

  if (already) {
    console.log('[main] Ollama already running.');
    return;
  }

  const ollamaExe = s.resolveOllamaExe();
  if (!ollamaExe) {
    console.warn('[main] Ollama binary not found — skipping.');
    return;
  }

  console.log('[main] Starting Ollama server…');
  ollamaProcess = s.startOllamaServer(ollamaExe);
  await s.waitForOllamaServer();
  console.log('[main] Ollama ready.');
}

// ─── App launch (after setup is done) ────────────────────────────────────────
async function launchApp() {
  try {
    await ensureOllamaRunning();

    // Detect architecture mode: if gateway/main.py exists, use 3-process
    const gatewayMain = path.join(GATEWAY_DIR, 'main.py');
    archMode = fs.existsSync(gatewayMain) ? 'multi' : 'legacy';
    console.log(`[main] Architecture mode: ${archMode}`);

    if (archMode === 'multi') {
      // 3-process architecture: Redis → Daemon → Engine → Gateway
      const installed = readInstalled();

      await startRedis();

      // Daemon: only if capture, modbus, ics-dnp3, exec, or topology is enabled
      const DAEMON_MODULES = ['capture', 'modbus', 'ics-dnp3', 'exec', 'topology'];
      if (DAEMON_MODULES.some(m => isModuleEnabled(installed, m))) {
        await startDaemon();
        // Brief pause for daemon to initialize
        await new Promise(r => setTimeout(r, 1500));
      } else {
        console.log('[main] Skipping Daemon (no daemon modules enabled).');
      }

      // Engine: only if llm-agent, rag, or expert-analysis is enabled
      const ENGINE_MODULES = ['llm-agent', 'rag', 'expert-analysis'];
      if (ENGINE_MODULES.some(m => isModuleEnabled(installed, m))) {
        await startEngine();
        // Brief pause for engine to initialize
        await new Promise(r => setTimeout(r, 1000));
      } else {
        console.log('[main] Skipping Engine (no engine modules enabled).');
      }

      await startGateway();
    } else {
      // Legacy single-process mode (fallback)
      await startBackend();
    }

    await waitForBackend(backendPort);
    console.log(`[main] Backend ready on port ${backendPort} (${archMode} mode)`);
    createMainWindow();
  } catch (err) {
    dialog.showErrorBox(
      'Failed to start NetScope',
      `${err.message}\n\nPlease re-run the setup or contact support.`
    );
    app.quit();
  }
}

// ─── App lifecycle ────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  const s = getSetup();

  if (s.isFirstRun()) {
    // Show the setup wizard; it calls wizard:finish when done
    createWizardWindow();
  } else {
    // Already set up — go straight to the app
    await launchApp();
  }
});

app.on('window-all-closed', () => {
  stopAllProcesses();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  stopAllProcesses();
});

app.on('activate', () => {
  if (mainWindow === null && app.isReady() && !wizardWindow) {
    launchApp();
  }
});
