# Wireshark AI Agent — Desktop (Electron)

An AI-powered network traffic analysis tool packaged as a Windows/macOS/Linux desktop application.

---

## Prerequisites

| Dependency | Purpose | Notes |
|---|---|---|
| **Python 3.11+** | Runs the FastAPI backend | Add to PATH during install |
| **Wireshark / tshark** | Live packet capture | Windows: also install **Npcap** |
| **Npcap** | Raw packet access on Windows | [npcap.com](https://npcap.com) |
| **Ollama** or **LM Studio** | Local LLM inference | Must be running before capture |
| **Node.js 18+** | Build toolchain (not needed at runtime) | Only for building the app |

---

## Quick start (development)

```bat
# 1. Set up the Python backend virtual environment (once)
scripts\setup_backend.bat

# 2. Install Electron + build tools
npm install

# 3. Build the React frontend
npm run build:frontend

# 4. Launch (Electron opens the app and starts the backend automatically)
npm start
```

---

## Build an installer

```bat
# Windows — produces dist-electron\Wireshark AI Agent Setup x.x.x.exe
npm run build

# macOS
npm run build:mac

# Linux
npm run build:linux
```

> **Before building** make sure `scripts\setup_backend.bat` has been run so
> the `.venv` directory exists inside `backend/`.  The installer bundles the
> whole `.venv` so end users do not need Python installed.

### Icons (required for installers)

Place the following files in the `assets/` directory:

| File | Format | Used for |
|---|---|---|
| `icon.ico` | Windows ICO (256×256) | Windows installer + app icon |
| `icon.icns` | macOS ICNS | macOS .dmg |
| `icon.png` | PNG 512×512 | Linux AppImage |

---

## Directory layout

```
netscope-desktop/
├── electron/
│   ├── main.js       ← Electron main process (spawns backend, opens window)
│   └── preload.js    ← Context bridge (exposes backend port to renderer)
├── backend/          ← Python FastAPI app (copied from project/backend)
│   ├── main.py
│   ├── requirements.txt
│   └── .venv/        ← Created by scripts/setup_backend.bat
├── frontend/         ← React + Vite app (copied from project/frontend)
│   └── dist/         ← Built by npm run build:frontend
├── assets/
│   ├── icon.ico      ← (add your own)
│   └── LICENSE.txt
├── scripts/
│   └── setup_backend.bat
├── package.json      ← Electron entry + electron-builder config
└── README.md
```

---

## How it works at runtime

1. Electron starts and calls `startBackend()` in `electron/main.js`.
2. The backend is launched as a child process:
   `<.venv>\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000`
3. Electron polls `http://127.0.0.1:8000/health` until the backend is ready.
4. The `BrowserWindow` loads `frontend/dist/index.html` as a `file://` page.
5. The port is injected into `window.__BACKEND_PORT__` so the React app builds
   correct API and WebSocket URLs.
6. On quit, Electron kills the entire backend process tree.

---

## Configuration

Copy `backend/.env.example` to `backend/.env` and edit as needed.

```env
LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen2.5:3b
```

At runtime, `PORT` and `HOST` are always overridden by the Electron main
process (to bind on loopback only).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Failed to start backend" dialog | Python not found / venv missing | Run `scripts\setup_backend.bat` |
| Blank white window | Frontend not built | Run `npm run build:frontend` |
| "No interfaces" in capture dropdown | tshark not on PATH | Install Wireshark and add tshark to PATH |
| No packet capture | Missing Npcap / not running as admin | Install Npcap; run app as Administrator |
| LLM not responding | Ollama/LM Studio not running | Start your local LLM before launching |
