"""
Exec tool: OpenClaw-style transparent elevation.

Mirrors OpenClaw's gateway routing model:
  1. Check if command is in ALWAYS_ELEVATED_CMDS → go straight to elevated
  2. Try command normally
  3. If exit code indicates permission denied → auto-retry elevated (no user prompt)
  4. Return the result — agent never has to think about elevation

The agent just calls: exec ipconfig /release
and the tool handles UAC/sudo automatically.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone

from agent.tools.registry import register, ToolDef
from utils.proc import SUBPROCESS_KWARGS

# ── Master kill-switch — disabled by default (CRITICAL security gate) ────────
# Set to True only via a trusted Settings IPC call; never auto-enable.
_EXEC_ENABLED: bool = False

# ── Safety: never run these regardless of mode ───────────────────────────────
BLOCKED_PATTERNS: frozenset[str] = frozenset({
    "rm -rf /", "format c:", "del /s /q c:", "rd /s /q c:",
    "shutdown", "reg delete", "diskpart", "mkfs.", "dd if=",
})

# ── Commands that always need admin — skip the normal-first attempt ───────────
# Matches the start of the command (after stripping whitespace)
ALWAYS_ELEVATED_PREFIXES: tuple[str, ...] = (
    "ipconfig /release",
    "ipconfig /renew",
    "ipconfig /flushdns",
    "netsh ",
    "net start",
    "net stop",
    "net use",
    "net user",
    "sc config",
    "sc start",
    "sc stop",
    "route add",
    "route delete",
    "route change",
    "arp -s",
    "arp -d",
    "set-netipaddress",
    "new-netipaddress",
    "remove-netipaddress",
    "set-dnsclientserveraddress",
    "enable-netadapter",
    "disable-netadapter",
    "restart-netadapter",
    "reg add",
    "reg delete",   # kept here even though also in blocked (blocked wins first)
    "schtasks /create",
    "schtasks /delete",
    "icacls",
    "takeown",
    "cacls",
    "wmic ",
)

# ── Strings in output that indicate a permission failure → auto-retry ─────────
PERMISSION_ERROR_SIGNALS: tuple[str, ...] = (
    "access is denied",
    "access denied",
    "requires elevation",
    "you must run",
    "run as administrator",
    "administrator privileges",
    "error 5",          # Windows ERROR_ACCESS_DENIED
    "error: 5",
    "permission denied",
    "operation requires",
    "requires administrator",
)


def _needs_elevation(command: str) -> bool:
    """Return True if the command is known to always require admin rights."""
    cmd_lower = command.strip().lower()
    return any(cmd_lower.startswith(p) for p in ALWAYS_ELEVATED_PREFIXES)


def _is_permission_error(output: str, exit_code: int) -> bool:
    """Return True if output/exit_code signals a permission failure."""
    out_lower = output.lower()
    return any(sig in out_lower for sig in PERMISSION_ERROR_SIGNALS)


async def _run_normal(command: str, timeout: int) -> tuple[int, str]:
    """Run command without elevation. Returns (exit_code, combined_output)."""
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **SUBPROCESS_KWARGS,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    combined = (
        stdout.decode("utf-8", errors="replace")
        + stderr.decode("utf-8", errors="replace")
    )
    return proc.returncode or 0, combined


async def _run_elevated_safe(command: str, timeout: int) -> tuple[int, str]:
    """Run command with elevation. Returns (exit_code, combined_output)."""
    from utils.elevate import run_elevated
    rc, stdout, stderr = await run_elevated(command, timeout=timeout)
    return rc, stdout + stderr


async def run_exec(args: str = "") -> str:
    if not _EXEC_ENABLED:
        return "[exec] Tool is disabled. Enable it via the Settings panel."

    from config import settings

    command = args.strip()
    if not command:
        return "[exec error] No command provided."

    # Safety gate — block destructive patterns
    cmd_lower = command.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in cmd_lower:
            return f"[exec error] Blocked dangerous pattern: '{pattern}'"

    timeout = settings.exec_timeout

    # ── Step 1: Known admin commands go straight to elevated ─────────────────
    if _needs_elevation(command):
        try:
            rc, combined = await _run_elevated_safe(command, timeout)
            _audit_log(command, rc, combined, elevated=True, auto=True)
            if not combined.strip():
                return f"[exec] Command finished with exit code {rc} (no output)."
            return combined
        except asyncio.TimeoutError:
            output = f"[exec error] Elevated command timed out after {timeout}s"
            _audit_log(command, -1, output, elevated=True, auto=True)
            return output
        except Exception as e:
            output = f"[exec error] {e}"
            _audit_log(command, -1, output, elevated=True, auto=True)
            return output

    # ── Step 2: Try normally ──────────────────────────────────────────────────
    try:
        try:
            exit_code, combined = await _run_normal(command, timeout)
        except asyncio.TimeoutError:
            output = f"[exec error] Command timed out after {timeout}s"
            _audit_log(command, -1, output)
            return output

    except Exception as e:
        output = f"[exec error] {e}"
        _audit_log(command, -1, output)
        return output

    # ── Step 3: Permission failure → auto-retry elevated ─────────────────────
    if _is_permission_error(combined, exit_code):
        try:
            rc, elevated_output = await _run_elevated_safe(command, timeout)
            _audit_log(command, rc, elevated_output, elevated=True, auto=True)
            if not elevated_output.strip():
                return f"[exec] Command finished with exit code {rc} (no output)."
            return elevated_output
        except asyncio.TimeoutError:
            output = f"[exec error] Elevated retry timed out after {timeout}s"
            _audit_log(command, -1, output, elevated=True, auto=True)
            return output
        except Exception as e:
            # Fall through and return original output if elevation also fails
            _audit_log(command, -1, f"[elevation failed] {e}", elevated=True, auto=True)

    _audit_log(command, exit_code, combined)
    if not combined.strip():
        return f"[exec] Command finished with exit code {exit_code} (no output)."
    return combined


def _audit_log(
    command: str,
    exit_code: int,
    output: str,
    elevated: bool = False,
    auto: bool = False,
) -> None:
    """Append a JSON line to data/exec_audit.jsonl (best-effort)."""
    try:
        audit_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
        audit_dir = os.path.normpath(audit_dir)
        os.makedirs(audit_dir, exist_ok=True)
        audit_path = os.path.join(audit_dir, "exec_audit.jsonl")
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": command,
            "exit_code": exit_code,
            "elevated": elevated,
            "auto_elevated": auto,
            "output_preview": output[:500],
        }
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # audit failure is non-fatal


# ── Registration ─────────────────────────────────────────────────────────────

register(ToolDef(
    name="exec", category="exec",
    description=(
        "Run any shell command. Handles privilege elevation automatically — "
        "if a command requires admin rights (ipconfig /release, netsh, route, "
        "Set-NetIPAddress, net, sc, reg, wmic, etc.) it escalates transparently "
        "without needing to be asked. Just pass the command directly."
    ),
    args_spec="<command>", runner=run_exec,
    safety="dangerous", always_available=True,
))

# exec_elevated kept as an alias for backwards compatibility
register(ToolDef(
    name="exec_elevated", category="exec",
    description="Alias for exec — elevation is now automatic. Prefer exec.",
    args_spec="<command>", runner=run_exec,
    safety="dangerous", always_available=True,
))
