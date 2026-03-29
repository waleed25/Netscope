# fetch_vendors.ps1
# Downloads all third-party binaries that are bundled inside the installer.
# Run once before `npm run build`.
#
# Downloads:
#   vendor/ollama.exe          - Ollama portable Windows binary
#   vendor/python-embed.zip    - Python 3.11 embeddable package (no installer needed)

param(
    [string]$PythonVersion = "3.11.9"
)

$ErrorActionPreference = "Stop"
$VendorDir = Join-Path $PSScriptRoot "..\vendor"
if (!(Test-Path $VendorDir)) { New-Item -ItemType Directory -Path $VendorDir | Out-Null }

# ── Ollama portable binary ────────────────────────────────────────────────────
$OllamaExe = Join-Path $VendorDir "ollama.exe"
if (!(Test-Path $OllamaExe)) {
    Write-Host "Downloading Ollama portable binary..."
    $OllamaUrl = "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.exe"
    Invoke-WebRequest -Uri $OllamaUrl -OutFile $OllamaExe -UseBasicParsing
    Write-Host "  -> $OllamaExe"
} else {
    Write-Host "Ollama already present, skipping."
}

# ── Python embeddable zip ─────────────────────────────────────────────────────
$PyZip = Join-Path $VendorDir "python-embed.zip"
if (!(Test-Path $PyZip)) {
    Write-Host "Downloading Python $PythonVersion embeddable package..."
    $PyUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    Invoke-WebRequest -Uri $PyUrl -OutFile $PyZip -UseBasicParsing
    Write-Host "  -> $PyZip"
} else {
    Write-Host "Python embed zip already present, skipping."
}

# ── pip bootstrap (get-pip.py) ────────────────────────────────────────────────
$GetPip = Join-Path $VendorDir "get-pip.py"
if (!(Test-Path $GetPip)) {
    Write-Host "Downloading get-pip.py..."
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip -UseBasicParsing
    Write-Host "  -> $GetPip"
} else {
    Write-Host "get-pip.py already present, skipping."
}

Write-Host ""
Write-Host "All vendors ready. You can now run: npm run build"
