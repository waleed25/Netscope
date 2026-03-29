"""
ATPA (Advanced Tool Poisoning Attack) defense utilities.

Sanitizes subprocess outputs and tool results before they enter the LLM
context window, stripping prompt-injection markers, control characters,
and other adversarial payloads that could hijack agent behaviour.
"""
from __future__ import annotations

import re
from typing import Sequence

# ── Injection pattern library ────────────────────────────────────────────────

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    # Directive impersonation
    re.compile(r"^\s*(SYSTEM\s*:|INSTRUCTION\s*:|IGNORE\s+PREVIOUS|OVERRIDE\s*:)", re.I),
    # Recursive tool dispatch (could trick the agent into calling tools)
    re.compile(r"^\s*TOOL\s*:", re.I),
    # Special-token markers used by various LLMs
    re.compile(r"<\|.*?\|>"),
    # ChatML-style injection
    re.compile(r"^\s*<\|?(system|user|assistant|im_start|im_end)\|?>", re.I),
    # Markdown-hidden directives (HTML comments with instructions)
    re.compile(r"<!--\s*(SYSTEM|INSTRUCTION|IGNORE|OVERRIDE)", re.I),
]

# ANSI escape sequences (colours, cursor movement, etc.)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# Null bytes and other C0 control chars except \n \r \t
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ── Public API ───────────────────────────────────────────────────────────────

def sanitize_tshark_output(raw: str, max_lines: int = 500) -> str:
    """Clean raw tshark stdout before it enters the LLM context.

    Layers:
    1. Strip ANSI escape codes (colour output from some tshark builds)
    2. Remove null bytes and non-printable control characters
    3. Drop lines matching known injection patterns
    4. Truncate to *max_lines* to bound token cost
    """
    if not raw:
        return ""

    # Strip ANSI + control chars
    cleaned = _ANSI_RE.sub("", raw)
    cleaned = _CONTROL_RE.sub("", cleaned)

    lines = cleaned.splitlines()
    safe: list[str] = []
    for line in lines:
        if any(pat.search(line) for pat in _INJECTION_PATTERNS):
            continue  # silently drop injection attempt
        safe.append(line)
        if len(safe) >= max_lines:
            safe.append(f"...[truncated at {max_lines} lines]")
            break

    return "\n".join(safe)


def sanitize_tool_output(raw: str, max_chars: int = 0) -> str:
    """ATPA defense applied to *every* tool result in dispatch().

    Preserves TOON table structure while removing:
    - Lines that look like prompt-injection directives
    - Unicode homoglyphs of ASCII control words (e.g. full-width SYSTEM)
    - Null bytes and control characters

    *max_chars*: optional hard truncation (0 = no limit; dispatch()
    applies its own MAX_OUTPUT cap afterwards).
    """
    if not raw:
        return ""

    # Normalise unicode confusables for the keywords we care about
    cleaned = _normalise_confusables(raw)

    # Strip control chars (keep \n \r \t for formatting)
    cleaned = _CONTROL_RE.sub("", cleaned)

    lines = cleaned.splitlines()
    safe: list[str] = []
    for line in lines:
        if any(pat.search(line) for pat in _INJECTION_PATTERNS):
            continue
        safe.append(line)

    result = "\n".join(safe)
    if max_chars > 0 and len(result) > max_chars:
        result = result[:max_chars] + "\n...[sanitized + truncated]"
    return result


def validate_read_only_command(cmd: Sequence[str]) -> bool:
    """Verify a subprocess command list contains no write operations.

    Used as a defence-in-depth check for tools with safety='read'
    before spawning subprocesses.
    """
    joined = " ".join(str(c) for c in cmd).lower()
    dangerous_tokens = [
        ">", ">>", " | ", " tee ", " rm ", " del ",
        " mv ", " move ", " cp ", " copy ",
        " rmdir ", " rd ", " mklink ",
    ]
    return not any(tok in joined for tok in dangerous_tokens)


# ── Internal helpers ─────────────────────────────────────────────────────────

# Map of full-width Latin letters → ASCII equivalents
_FULLWIDTH_MAP = str.maketrans(
    {chr(0xFF01 + i): chr(0x21 + i) for i in range(94)}
)


def _normalise_confusables(text: str) -> str:
    """Convert full-width Unicode characters to ASCII equivalents.

    This prevents attackers from using visually similar characters
    (e.g. \uff34\uff2f\uff2f\uff2c = 'TOOL' in full-width) to bypass
    the injection pattern filters.
    """
    return text.translate(_FULLWIDTH_MAP)
