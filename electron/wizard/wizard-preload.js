'use strict';

/**
 * wizard-preload.js
 * Preload script for the first-run wizard window.
 * Exposes a typed bridge from the renderer to main-process IPC handlers.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('wizardBridge', {
  /** Detect NVIDIA GPU and return { hasGpu, vramGB, gpuName } */
  detectGpu: () => ipcRenderer.invoke('wizard:detectGpu'),

  /** Given vramGB, return the best model entry { model, label, minVramGB } */
  pickModel: (vramGB) => ipcRenderer.invoke('wizard:pickModel', vramGB),

  /**
   * Run the full setup sequence.
   * Returns a promise that resolves with { ollamaExe, modelName, gpu } on success.
   * Progress events are delivered via onProgress().
   */
  runSetup: () => ipcRenderer.invoke('wizard:runSetup'),

  /**
   * Subscribe to progress events emitted during runSetup.
   * cb receives { stage, message, percent }.
   */
  onProgress: (cb) => {
    ipcRenderer.on('wizard:progress', (_event, data) => cb(data));
  },

  /** Signal that the wizard is done — main process closes this window and opens the app. */
  finishSetup: (selectedModules) => ipcRenderer.send('wizard:finish', { selectedModules }),

  /** Detect hardware capabilities — returns { gpu_vram_gb, gpu_name, ram_gb, npcap, libpcap, os, disk_free_gb } */
  detectCapabilities: () => ipcRenderer.invoke('wizard:detectCapabilities'),

  /** Get available modules from manifests — returns array of { name, description, optional, needs_npcap, ram_gb_min } */
  getModules: () => ipcRenderer.invoke('wizard:getModules'),
});
