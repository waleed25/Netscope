# NetScope — Agent Handoff Document
**Written:** 2026-04-03
**Project:** C:\Users\ffd\Documents\netscope-desktop
**Task:** Security hardening + offline standalone EXE packaging

---

## What Has Been Done

### Security Fixes Applied (DONE — do NOT redo these)

| ID | File | Fix Applied |
|----|------|-------------|
| ELEC-01 | `electron/main.js` line 445 | `webSecurity: IS_PACKAGED` → `webSecurity: true` |
| ELEC-03 | `electron/main.js` line 477 | CSP `connect-src` locked to `127.0.0.1:${backendPort}` (not all ports) |
| ELEC-05 | `electron/main.js` line ~503 | `webSecurity: true` added to wizard window `webPreferences` |
| MISC-02 | `electron/main.js` line 455 | `openDevTools()` now guarded by `process.env.DEVTOOLS === '1'` |
| API-05 | `backend/main.py` line 107 | Removed `"null"` from CORS origins (was CSRF vector) |
| MISC-01 | `backend/config.py` line 54 | Removed `"file://"` from `cors_origins` default list |
| API-07 | `backend/api/modbus_routes.py` line 96 | Simulator default host `"0.0.0.0"` → `"127.0.0.1"` |
| API-12 | `backend/api/modbus_routes.py` line 108 | `WriteRegisterRequest` address/value get `Field(..., ge=0, le=65535)` |
| API-04 | `backend/api/modbus_routes.py` ~line 396 | `_validate_log_path()` now called before `create_session()` in `create_client_session` |

---

## What Still Needs To Be Done

### A. Remaining Security Fixes

**API-06 — Sanitise tool output before LLM prompt injection**
File: `backend/api/routes.py` around line 1070–1081
Problem: `req.output` is inserted raw into LLM prompt — prompt injection risk.
Fix: Apply existing `_safe_str()` to `req.output` and cap at 8192 chars. Also add `max_length=8192` to the `ToolAnalyzeRequest` Pydantic model.

```python
# In ToolAnalyzeRequest model (find it above the endpoint, add):
output: str = Field(..., max_length=8192)

# In analyze_tool_output endpoint, change:
f"Here is the output:\n\n```\n{req.output}\n```\n\n"
# to:
f"Here is the output:\n\n```\n{_safe_str(req.output)[:8192]}\n```\n\n"
```

**API-11 — SSRF check missing on /rag/ingest/url**
File: `backend/api/rag_routes.py` around line 216–238
Problem: `ingest_url` passes user-supplied URL to markitdown without SSRF validation.
Fix: Import `_is_safe_url` from `rag.crawler` and call it before enqueuing background task.

```python
# At top of rag_routes.py add import:
from rag.crawler import _is_safe_url

# In ingest_url(), after url = req.url.strip(), before task creation:
safe, reason = _is_safe_url(url)
if not safe:
    raise HTTPException(status_code=400, detail=f"URL not allowed: {reason}")
```

**AGENT-02 — No target validation in agent network tools**
File: `backend/agent/tools/network.py` lines 59–73
Problem: `run_ping`, `run_tracert`, `run_arp` pass unsanitised `args` directly to subprocess argv.
Fix: Import `_validate_target` from `api.routes` and apply it.

```python
# At top of network.py add:
from api.routes import _validate_target

# In run_ping:
async def run_ping(args: str) -> str:
    raw = args.strip() or "8.8.8.8"
    host = _validate_target(raw) or "8.8.8.8"
    return await _run_sync(_run_subprocess, [_EXECUTABLES["ping"], "-n", "4", host])

# Same pattern for run_tracert and run_arp
```

**MOD-02 — Pairing code uses non-cryptographic random**
File: `backend/channels/config_store.py` line 88
Fix: Replace `random.randint(100000, 999999)` with `secrets.randbelow(900000) + 100000`
Also add `import secrets` to the imports at the top (line ~8).

**API-01 — exec tool shell command injection (CRITICAL)**
File: `backend/agent/tools/exec.py`
Problem: `asyncio.create_subprocess_shell()` with LLM-controlled input + trivially bypassable denylist.
Fix: Add a module-level flag `_EXEC_ENABLED = False`. At the top of `run_exec()`, check:
```python
if not _EXEC_ENABLED:
    return "[exec] Tool is disabled. Enable it via the Settings panel."
```
The UI can expose a toggle to set this flag via an IPC call. This gates the tool without removing it.

**API-02 — elevate.py writes LLM command into bat file unsanitised (CRITICAL)**
File: `backend/utils/elevate.py` lines 72–78
Problem: `command` from LLM goes verbatim into a batch file run as Admin.
Fix: Same `_EXEC_ENABLED` gate — since `_run_elevated_windows` is only called from `exec.py`, disabling exec disables this path too. Additionally add a length cap:
```python
if len(command) > 1024:
    raise ValueError("Command too long")
```

**FE-02 — __BACKEND_PORT__ window fallback**
File: `frontend/src/lib/api.ts` lines ~20–23
Fix: Remove the `window.__BACKEND_PORT__` fallback branch entirely. Use only `electronBridge.getBackendPort()`.

**ELEC-02 — setWindowOpenHandler doesn't validate domain**
File: `electron/main.js` lines 458–466
Current code opens any `http:`/`https:` URL externally. This is acceptable but could be tightened.
Low priority — leave for now unless packaging is done first.

**ELEC-06 — execSync taskkill uses template string with PID**
File: `electron/main.js` lines ~174–176
Fix: Replace `execSync(\`taskkill /PID ${proc.pid}\`)` with `spawnSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'])`.
Import `spawnSync` from `child_process` if not already imported.

---

### B. Packaging — Build Offline Standalone EXE

The app uses **embedded Python** (not PyInstaller). The strategy is:
1. Ship `vendor/python-embed.zip` (Python 3.11 embeddable, ~7 MB)
2. Pre-populate `.pyembed/` with all pip packages at **build time** so users need zero internet
3. Bundle everything with electron-builder NSIS installer

#### Step 1 — Fix `setup.js` RESOURCES path bug
File: `electron/setup.js` lines 30–31
Current (broken for some install paths):
```js
const RESOURCES = IS_PACKAGED
  ? require('electron').app.getPath('exe').replace(/[^/\\]+$/, '') + 'resources'
  : path.join(__dirname, '..');
```
Fix — use `process.resourcesPath` (same as main.js):
```js
const RESOURCES = IS_PACKAGED
  ? process.resourcesPath
  : path.join(__dirname, '..');
```

#### Step 2 — Create missing icon assets
electron-builder will FAIL without these two files:
- `assets/icon.ico` — 256×256 multi-resolution Windows ICO
- `assets/installer-sidebar.bmp` — 164×314 BMP for NSIS sidebar

Create placeholder/real icons. Can use ImageMagick or Python Pillow:
```bash
# With Python Pillow (install if needed: pip install Pillow):
python -c "
from PIL import Image, ImageDraw
img = Image.new('RGBA', (256, 256), '#0d1117')
d = ImageDraw.Draw(img)
d.ellipse([40,40,216,216], fill='#58a6ff')
img.save('assets/icon.ico', format='ICO', sizes=[(256,256),(128,128),(64,64),(32,32),(16,16)])
bmp = Image.new('RGB', (164, 314), '#0d1117')
bmp.save('assets/installer-sidebar.bmp')
"
```

#### Step 3 — Pre-populate .pyembed at build time (offline install)
Run these commands in order BEFORE `electron-builder`:
```powershell
# 1. Extract embedded Python
Expand-Archive vendor\python-embed.zip -DestinationPath vendor\.pyembed-build -Force

# 2. Enable site-packages (patch the ._pth file)
$pth = Get-ChildItem vendor\.pyembed-build -Filter "*._pth" | Select-Object -First 1
(Get-Content $pth.FullName) -replace '#import site','import site' | Set-Content $pth.FullName
Add-Content $pth.FullName "Lib\site-packages"

# 3. Install pip
vendor\.pyembed-build\python.exe vendor\get-pip.py --no-warn-script-location

# 4. Install PyTorch CPU (largest dep, ~700MB)
vendor\.pyembed-build\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu --no-warn-script-location

# 5. Install all other requirements
vendor\.pyembed-build\python.exe -m pip install -r backend\requirements.txt --no-warn-script-location

# 6. Write stamp file so setup wizard skips reinstall
echo "offline-prebundled" > vendor\.pyembed-build\.requirements_installed
```

#### Step 4 — Update electron-builder extraResources in package.json
Open `package.json`, find the `"build"` key, and ADD to `extraResources`:
```json
{ "from": "vendor/.pyembed-build", "to": "backend/.pyembed" }
```
Also verify `vendor/` is in `files` or `extraResources`.

#### Step 5 — (Optional) Pre-download HuggingFace model for fully offline RAG
```powershell
$env:TRANSFORMERS_CACHE = "vendor\hf_cache"
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```
Then add to `extraResources`: `{ "from": "vendor/hf_cache", "to": "vendor/hf_cache" }`
And in `main.js` `_buildPythonEnv()`: `TRANSFORMERS_CACHE: path.join(VENDOR_DIR, 'hf_cache'), HF_HUB_OFFLINE: '1'`

#### Step 6 — Run build
```bat
scripts\build.bat
```
Or manually:
```bat
cd frontend && npm install && npm run build && cd ..
npx electron-builder --win --x64
```
Output: `dist-electron\NetScope Setup X.X.X.exe`

#### Step 7 — Verify
- Install the EXE on a clean VM with no Python, no Node, no internet
- First launch should show the setup wizard, skip the pip install step (stamp file present)
- Wireshark/tshark must be pre-installed separately (cannot be bundled — requires Npcap kernel driver)

---

## Key File Reference

| File | Purpose |
|------|---------|
| `electron/main.js` | Electron lifecycle, Python spawn, IPC, CSP |
| `electron/setup.js` | First-run wizard, Python bootstrap |
| `electron/preload.js` | Context bridge (port IPC) |
| `backend/main.py` | FastAPI app, CORS, router registration |
| `backend/config.py` | Pydantic settings (env-configurable) |
| `backend/api/routes.py` | Main REST endpoints |
| `backend/api/modbus_routes.py` | Modbus TCP endpoints |
| `backend/api/rag_routes.py` | RAG/knowledge base endpoints |
| `backend/agent/tools/exec.py` | Shell exec tool (CRITICAL — needs gate) |
| `backend/agent/tools/network.py` | ping/tracert/arp agent tools |
| `backend/utils/elevate.py` | UAC elevation helper |
| `backend/channels/config_store.py` | Pairing code generation |
| `backend/rag/crawler.py` | SSRF-protected URL crawler (`_is_safe_url`) |
| `frontend/src/lib/api.ts` | Axios client, port resolution |
| `assets/` | Icon and installer assets (NEED icon.ico + sidebar.bmp) |
| `package.json` | electron-builder config in `"build"` key |
| `scripts/build.bat` | One-click build script |
| `scripts/fetch_vendors.ps1` | Downloads vendor binaries |

---

## Conventions
- Dark theme: `#0d1117`, `#161b22`, `#30363d`, `#58a6ff`
- All components in `frontend/src/components/`
- Backend settings in `backend/config.py` (pydantic-settings)
- No external toast library — use `toast` from `./Toast`
- Do not restart the backend via preview_stop/preview_start unless needed — it loses state
