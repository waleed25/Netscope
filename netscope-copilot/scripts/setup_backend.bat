@echo off
REM =========================================================================
REM  setup_backend.bat
REM  Creates/updates the Python virtual environment embedded in the Electron
REM  package.  Run this once before `npm run build` or `npm start`.
REM
REM  Requirements:
REM    - Python 3.11+ on PATH
REM    - Internet access (to download packages from PyPI / PyTorch CDN)
REM =========================================================================

setlocal

set SCRIPT_DIR=%~dp0
set BACKEND_DIR=%SCRIPT_DIR%..\backend
set VENV_DIR=%BACKEND_DIR%\.venv

echo.
echo === Wireshark AI Agent — Backend Setup ===
echo.

REM ---- Check Python --------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found on PATH.
    echo Please install Python 3.11+ from https://python.org and re-run this script.
    pause
    exit /b 1
)

for /f "delims=" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Found: %PYVER%

REM ---- Create venv if it doesn't exist ------------------------------------
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment in %VENV_DIR% ...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo Virtual environment already exists, updating dependencies...
)

REM ---- Upgrade pip ---------------------------------------------------------
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip --quiet

REM ---- Install CPU-only PyTorch first (smaller download) ------------------
REM  For CUDA support, comment out the line below and uncomment the CUDA line.
echo Installing PyTorch (CPU)...
"%VENV_DIR%\Scripts\pip.exe" install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu --quiet
REM  CUDA 12.4 version (uncomment if the target machine has an NVIDIA GPU):
REM "%VENV_DIR%\Scripts\pip.exe" install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 --quiet

REM ---- Install all other requirements -------------------------------------
echo Installing Python requirements...
"%VENV_DIR%\Scripts\pip.exe" install -r "%BACKEND_DIR%\requirements.txt" --quiet
if errorlevel 1 (
    echo ERROR: pip install failed. Check your internet connection and try again.
    pause
    exit /b 1
)

echo.
echo === Backend setup complete! ===
echo You can now run:  npm start
echo.
endlocal
