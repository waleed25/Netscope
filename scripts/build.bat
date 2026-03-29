@echo off
REM =========================================================================
REM  build.bat — One-click build script for NetScope
REM  Produces: dist-electron\NetScope Setup 1.0.0.exe
REM
REM  Prerequisites (on the BUILD machine only):
REM    - Node.js 18+
REM    - Python 3.11+ (only needed to verify requirements.txt syntax)
REM    - Internet access (to download vendor binaries and npm packages)
REM
REM  END USERS do NOT need Python, Node, or Ollama pre-installed.
REM  Everything is bundled inside the installer.
REM =========================================================================

setlocal
set SCRIPT_DIR=%~dp0
set ROOT=%SCRIPT_DIR%..

echo.
echo === NetScope — Build ===
echo.

REM ── 1. Fetch vendor binaries ──────────────────────────────────────────────
echo [1/4] Fetching vendor binaries (ollama.exe, python-embed.zip)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%fetch_vendors.ps1"
if errorlevel 1 ( echo ERROR: fetch_vendors.ps1 failed. & pause & exit /b 1 )

REM ── 2. Install npm dependencies ───────────────────────────────────────────
echo [2/4] Installing npm dependencies...
call npm install --prefix "%ROOT%"
if errorlevel 1 ( echo ERROR: npm install failed. & pause & exit /b 1 )

REM ── 3. Build React frontend ───────────────────────────────────────────────
echo [3/4] Building React frontend...
call npm install --prefix "%ROOT%\frontend"
if errorlevel 1 ( echo ERROR: frontend npm install failed. & pause & exit /b 1 )
call npm run build --prefix "%ROOT%\frontend"
if errorlevel 1 ( echo ERROR: frontend build failed. & pause & exit /b 1 )

REM ── 4. Package with electron-builder ─────────────────────────────────────
echo [4/4] Packaging Electron installer...
call npx electron-builder --win --x64 --project "%ROOT%"
if errorlevel 1 ( echo ERROR: electron-builder failed. & pause & exit /b 1 )

echo.
echo === Build complete! ===
echo Installer: %ROOT%\dist-electron\NetScope Setup 1.0.0.exe
echo.
endlocal
