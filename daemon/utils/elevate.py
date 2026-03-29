"""
Elevated command execution (OpenClaw-style gateway elevation).

On Windows: writes command to a temp .bat file, launches it via
ShellExecuteW with the "runas" verb (triggers UAC), captures output
via a temp result file.

On Linux/macOS: prefixes with sudo (assumes passwordless sudo or
the backend is already running as root).
"""

import asyncio
import os
import sys
import tempfile
from asyncio.subprocess import PIPE

from utils.proc import SUBPROCESS_KWARGS


async def run_elevated(command: str, timeout: int = 30) -> tuple[int, str, str]:
    """
    Run *command* with elevated privileges.

    Returns (returncode, stdout, stderr).
    Raises asyncio.TimeoutError if the command exceeds *timeout* seconds.
    """
    if sys.platform == "win32":
        return await _run_elevated_windows(command, timeout)
    else:
        return await _run_elevated_unix(command, timeout)


async def _run_elevated_unix(command: str, timeout: int) -> tuple[int, str, str]:
    """Prefix with sudo on Linux/macOS."""
    full_cmd = f"sudo {command}"
    proc = await asyncio.create_subprocess_shell(
        full_cmd,
        stdout=PIPE,
        stderr=PIPE,
        **SUBPROCESS_KWARGS,
    )
    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return (
        proc.returncode or 0,
        stdout_b.decode(errors="replace"),
        stderr_b.decode(errors="replace"),
    )


async def _run_elevated_windows(command: str, timeout: int) -> tuple[int, str, str]:
    """
    On Windows, spawn an elevated cmd.exe via ShellExecuteW("runas").

    Flow:
    1. Write command to a temp .bat file.
    2. Write stdout/stderr redirect paths to the .bat file.
    3. ShellExecuteW the .bat with "runas" verb (UAC prompt).
    4. Poll for the output file to appear (up to *timeout* seconds).
    5. Read and return the captured output.
    """
    import ctypes

    # Temp directory for I/O files
    tmp = tempfile.mkdtemp(prefix="netscope_elev_")
    bat_path = os.path.join(tmp, "cmd.bat")
    out_path = os.path.join(tmp, "stdout.txt")
    err_path = os.path.join(tmp, "stderr.txt")
    done_path = os.path.join(tmp, "done.flag")

    # Write .bat that runs the command, redirects output, writes done flag
    bat_content = (
        f"@echo off\r\n"
        f"({command}) > \"{out_path}\" 2> \"{err_path}\"\r\n"
        f"echo %ERRORLEVEL% > \"{done_path}\"\r\n"
    )
    with open(bat_path, "w") as f:
        f.write(bat_content)

    # ShellExecuteW with "runas" verb — this shows the UAC dialog
    ret = ctypes.windll.shell32.ShellExecuteW(
        None,           # hwnd
        "runas",        # verb
        "cmd.exe",      # file
        f"/c \"{bat_path}\"",  # parameters
        None,           # directory
        0,              # nShowCmd (SW_HIDE)
    )

    if ret <= 32:  # ShellExecuteW returns > 32 on success
        return (1, "", f"[elevation error] ShellExecuteW failed with code {ret}. UAC may have been denied.")

    # Poll for done.flag
    elapsed = 0.0
    poll_interval = 0.25
    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        if os.path.exists(done_path):
            break
    else:
        return (1, "", "[elevation error] Command timed out waiting for elevated process.")

    # Read captured output
    try:
        with open(out_path, "r", errors="replace") as f:
            stdout = f.read()
    except FileNotFoundError:
        stdout = ""

    try:
        with open(err_path, "r", errors="replace") as f:
            stderr = f.read()
    except FileNotFoundError:
        stderr = ""

    try:
        with open(done_path, "r") as f:
            rc_str = f.read().strip()
        returncode = int(rc_str) if rc_str.isdigit() else 0
    except Exception:
        returncode = 0

    # Cleanup temp files (best-effort)
    for p in [bat_path, out_path, err_path, done_path]:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(tmp)
    except OSError:
        pass

    return (returncode, stdout, stderr)
