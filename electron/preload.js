'use strict';

/**
 * Electron preload script
 *
 * Runs in the renderer process but with Node.js access before the page loads.
 * We use it to expose the backend port (injected by the main process) so that
 * the React app can construct correct API and WebSocket URLs at runtime.
 *
 * Security model:
 *  - contextIsolation: true   — the renderer cannot access Node APIs directly.
 *  - Only the minimum required information is bridged via contextBridge.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronBridge', {
  /**
   * Returns the port the Python backend is listening on.
   * Uses a synchronous IPC call so the port is available before React mounts,
   * eliminating the dom-ready race condition from the previous executeJavaScript approach.
   */
  getBackendPort: () => ipcRenderer.sendSync('get-backend-port') || 8000,

  /** Open a URL in the user's default browser (http/https only; validated in main) */
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  /** Restart the Python backend process and wait until it is healthy again. */
  restartBackend: () => ipcRenderer.invoke('restart-backend'),
});
