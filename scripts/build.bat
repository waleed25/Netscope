@echo off
REM =========================================================================
REM  build.bat — One-click build script for NetScope
REM  Produces: dist-electron\NetScope Setup 1.1.0.exe
REM
REM  Prerequisites (on the BUILD machine only):
REM    - Node.js 18+
REM    - Internet access (first run only — to download vendor binaries + pip packages)
REM
REM  END USERS do NOT need Python, Node, or Ollama pre-installed.
REM  Everything is bundled inside the installer (offline-capable after first build).
REM =========================================================================

setlocal
set SCRIPT_DIR=%~dp0
set ROOT=%SCRIPT_DIR%..
set PYEMBED=%ROOT%\vendor\.pyembed-build

echo.
echo === NetScope — Build ===
echo.

REM ── 1. Fetch vendor binaries ──────────────────────────────────────────────
echo [1/5] Fetching vendor binaries (ollama.exe, python-embed.zip)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%fetch_vendors.ps1"
if errorlevel 1 ( echo ERROR: fetch_vendors.ps1 failed. & pause & exit /b 1 )

REM ── 2. Bootstrap offline Python environment ───────────────────────────────
echo [2/5] Bootstrapping offline Python environment...
if not exist "%PYEMBED%\python.exe" (
    echo   Extracting python-embed.zip...
    powershell -NoProfile -Command "Expand-Archive '%ROOT%\vendor\python-embed.zip' -DestinationPath '%PYEMBED%' -Force"
    if errorlevel 1 ( echo ERROR: Failed to extract python-embed.zip. & pause & exit /b 1 )

    echo   Patching ._pth to enable site-packages...
    powershell -NoProfile -Command ^
        "$pth = Get-ChildItem '%PYEMBED%' -Filter '*._pth' | Select-Object -First 1;" ^
        "(Get-Content $pth.FullName) -replace '#import site','import site' | Set-Content $pth.FullName;" ^
        "Add-Content $pth.FullName 'Lib\site-packages'"

    echo   Installing pip...
    "%PYEMBED%\python.exe" "%ROOT%\vendor\get-pip.py" --no-warn-script-location -q
    if errorlevel 1 ( echo ERROR: pip install failed. & pause & exit /b 1 )

    echo   Installing PyTorch CPU (~700 MB, this may take a while)...
    "%PYEMBED%\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/cpu --no-warn-script-location -q
    if errorlevel 1 ( echo ERROR: torch install failed. & pause & exit /b 1 )

    echo   Installing backend requirements...
    "%PYEMBED%\python.exe" -m pip install -r "%ROOT%\backend\requirements.txt" --no-warn-script-location -q
    if errorlevel 1 ( echo ERROR: requirements install failed. & pause & exit /b 1 )

    echo   Writing stamp file...
    echo offline-prebundled > "%PYEMBED%\.requirements_installed"
    echo   Python environment ready.
) else (
    echo   Python environment already bootstrapped, skipping.
)

REM ── 3. Install npm dependencies ───────────────────────────────────────────
echo [3/5] Installing npm dependencies...
call npm install --prefix "%ROOT%"
if errorlevel 1 ( echo ERROR: npm install failed. & pause & exit /b 1 )

REM ── 4. Build React frontend ───────────────────────────────────────────────
echo [4/5] Building React frontend...
call npm install --prefix "%ROOT%\frontend"
if errorlevel 1 ( echo ERROR: frontend npm install failed. & pause & exit /b 1 )
call npm run build --prefix "%ROOT%\frontend"
if errorlevel 1 ( echo ERROR: frontend build failed. & pause & exit /b 1 )

REM ── 5. Package with electron-builder ─────────────────────────────────────
echo [5/5] Packaging Electron installer...
call npx electron-builder --win --x64 --project "%ROOT%"
if errorlevel 1 ( echo ERROR: electron-builder failed. & pause & exit /b 1 )

echo.
echo === Build complete! ===
echo Installer: %ROOT%\dist-electron\NetScope Setup 1.1.0.exe
echo.
endlocal
