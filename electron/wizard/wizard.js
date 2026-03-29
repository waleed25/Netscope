'use strict';
/* global window, document */

/**
 * wizard.js — Renderer-side logic for the first-run setup wizard.
 *
 * Communicates with the main process via window.wizardBridge (exposed by
 * wizard-preload.js through contextBridge).
 */

const bridge = window.wizardBridge;

// ── State ────────────────────────────────────────────────────────────────────
let currentSlide = 0;
const TOTAL_SLIDES = 6;
let gpuResult   = null;
let modelResult = null;

// ── DOM refs ─────────────────────────────────────────────────────────────────
const nextBtn     = document.getElementById('nextBtn');
const slides      = Array.from({ length: TOTAL_SLIDES }, (_, i) =>
  document.getElementById(`slide-${i}`)
);
const stepDots    = document.getElementById('stepDots');
const progressBar = document.getElementById('progressBar');
const statusLabel = document.getElementById('statusLabel');
const logBox      = document.getElementById('logBox');

// ── Step dots ─────────────────────────────────────────────────────────────────
function renderDots() {
  stepDots.innerHTML = '';
  for (let i = 0; i < TOTAL_SLIDES; i++) {
    const d = document.createElement('div');
    d.className = 'step-dot' +
      (i === currentSlide ? ' active' : '') +
      (i < currentSlide  ? ' done'   : '');
    stepDots.appendChild(d);
  }
}

// ── Slide transitions ─────────────────────────────────────────────────────────
function goToSlide(n) {
  const prev = slides[currentSlide];
  prev.classList.remove('visible');
  prev.classList.add('exit');
  setTimeout(() => prev.classList.remove('exit'), 350);

  currentSlide = n;
  slides[currentSlide].classList.add('visible');
  renderDots();
}

// ── Log helpers ───────────────────────────────────────────────────────────────
function appendLog(text, cls = 'active') {
  const line = document.createElement('div');
  line.className = `log-line ${cls}`;
  line.textContent = text;
  logBox.appendChild(line);
  logBox.scrollTop = logBox.scrollHeight;
}

function setProgress(pct, done = false) {
  progressBar.style.width = `${pct}%`;
  if (done) progressBar.classList.add('done');
}

function setStatus(text) {
  statusLabel.textContent = text;
}

// ── Slide 1: GPU detection ────────────────────────────────────────────────────
async function runGpuDetection() {
  nextBtn.disabled = true;
  const gpuIcon   = document.getElementById('gpuIcon');
  const gpuName   = document.getElementById('gpuName');
  const gpuDetail = document.getElementById('gpuDetail');
  const modelLine = document.getElementById('modelLine');
  const modelBadge = document.getElementById('modelBadge');

  const result = await bridge.detectGpu();
  gpuResult   = result;
  modelResult = await bridge.pickModel(result.vramGB);

  if (result.hasGpu) {
    gpuIcon.textContent  = '🎮';
    gpuName.textContent  = result.gpuName;
    gpuDetail.textContent = `${result.vramGB} GB VRAM detected`;
  } else {
    gpuIcon.textContent  = '💻';
    gpuName.textContent  = 'No NVIDIA GPU detected';
    gpuDetail.textContent = 'Will use CPU inference';
  }

  modelLine.style.display = '';
  modelBadge.textContent  = modelResult.model;

  nextBtn.disabled = false;
  nextBtn.textContent = 'Continue';
}

// ── Slide 2: Installation ─────────────────────────────────────────────────────
async function runInstallation() {
  nextBtn.disabled = true;
  nextBtn.textContent = 'Installing…';

  // Listen to progress events from the main process
  bridge.onProgress((evt) => {
    const { stage, message, percent } = evt;
    appendLog(`[${stage}] ${message}`, percent === 100 ? 'success' : 'active');
    setStatus(message);
    setProgress(percent);
  });

  try {
    const setupResult = await bridge.runSetup();

    setProgress(100, true);
    setStatus('Installation complete.');
    appendLog('All done!', 'success');

    // Populate done slide
    buildDoneSlide(setupResult);

    nextBtn.disabled  = false;
    nextBtn.textContent = 'Launch NetScope';
    nextBtn.className   = 'btn btn-success';

    goToSlide(3);
  } catch (err) {
    appendLog(`ERROR: ${err.message}`, 'error');
    setStatus('Setup failed — see log above.');
    nextBtn.disabled = false;
    nextBtn.textContent = 'Retry';
    nextBtn.onclick = () => location.reload();
  }
}

// ── Slide 3: Done ─────────────────────────────────────────────────────────────
function buildDoneSlide(result) {
  const grid = document.getElementById('specGrid');
  const specs = [
    { label: 'AI Model',   value: result.modelName },
    { label: 'GPU',        value: result.gpu.hasGpu ? result.gpu.gpuName : 'CPU (no GPU)' },
    { label: 'VRAM',       value: result.gpu.hasGpu ? `${result.gpu.vramGB} GB` : 'N/A' },
    { label: 'Inference',  value: result.gpu.hasGpu ? 'GPU (Ollama CUDA)' : 'CPU' },
  ];
  grid.innerHTML = specs.map(s => `
    <div class="spec-item">
      <div class="label">${s.label}</div>
      <div class="value">${s.value}</div>
    </div>
  `).join('');
}

// ── Slide 4: Capabilities detection ──────────────────────────────────────────
async function runCapabilitiesDetection() {
  document.getElementById('caps-spinner').style.display = 'block';
  document.getElementById('caps-result').style.display = 'none';

  const caps = await bridge.detectCapabilities();
  window._detectedCaps = caps;

  document.getElementById('cap-gpu').textContent =
    caps.gpu_vram_gb > 0 ? `${caps.gpu_name || 'GPU'} (${caps.gpu_vram_gb} GB)` : 'Not detected';
  document.getElementById('cap-ram').textContent = `${caps.ram_gb} GB`;
  document.getElementById('cap-os').textContent = caps.os || 'Unknown';
  document.getElementById('cap-capture').textContent =
    caps.npcap ? 'Npcap ✓' : caps.libpcap ? 'libpcap ✓' : 'Not installed';
  document.getElementById('cap-disk').textContent = `${caps.disk_free_gb} GB free`;

  document.getElementById('caps-spinner').style.display = 'none';
  document.getElementById('caps-result').style.display = 'block';
}

document.getElementById('btn-to-modules').addEventListener('click', () => {
  goToSlide(5);
  showModulesScreen();
});

// ── Slide 5: Module selection ─────────────────────────────────────────────────
async function showModulesScreen() {
  const modules = await bridge.getModules();
  const list = document.getElementById('modules-list');
  list.innerHTML = '';

  modules.forEach(mod => {
    const item = document.createElement('div');
    item.className = 'module-item';
    const caps = window._detectedCaps || {};
    const incompatible = (mod.needs_npcap && !caps.npcap) ||
                         (mod.ram_gb_min > 0 && caps.ram_gb > 0 && caps.ram_gb < mod.ram_gb_min);
    item.innerHTML = `
      <input type="checkbox" id="mod-${mod.name}" value="${mod.name}"
             ${!mod.optional ? 'checked disabled' : 'checked'}
             ${incompatible ? 'disabled' : ''}>
      <div>
        <div class="module-name">${mod.name}${incompatible ? ' <span style="color:#f85149;font-size:11px">(incompatible)</span>' : ''}</div>
        <div class="module-desc">${mod.description || ''}</div>
      </div>`;
    list.appendChild(item);
  });

  // If no modules found (modules/ dir doesn't exist yet), show a message
  if (modules.length === 0) {
    list.innerHTML = '<div class="slide-desc" style="padding:12px">No modules found — all features will be enabled by default.</div>';
  }
}

document.getElementById('btn-modules-all').addEventListener('click', () => {
  document.querySelectorAll('#modules-list input[type=checkbox]:not([disabled])').forEach(cb => {
    cb.checked = true;
  });
});

document.getElementById('btn-modules-finish').addEventListener('click', () => {
  const selected = [];
  document.querySelectorAll('#modules-list input[type=checkbox]').forEach(cb => {
    if (cb.checked) selected.push(cb.value);
  });
  bridge.finishSetup(selected);
});

// ── Button handler ────────────────────────────────────────────────────────────
nextBtn.addEventListener('click', async () => {
  if (currentSlide === 0) {
    goToSlide(1);
    nextBtn.textContent = 'Scanning…';
    nextBtn.disabled = true;
    await runGpuDetection();
  } else if (currentSlide === 1) {
    goToSlide(2);
    await runInstallation();
  } else if (currentSlide === 3) {
    goToSlide(4);
    nextBtn.style.display = 'none';
    await runCapabilitiesDetection();
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────
renderDots();
