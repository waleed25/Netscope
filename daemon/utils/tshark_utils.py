"""
Shared tshark discovery utility.

Centralises the logic for locating the tshark binary so it is not duplicated
across capture/, modbus/, and ics/ modules.
"""

from __future__ import annotations
import os
import shutil
from typing import Optional

_WINDOWS_PATHS = [
    r"C:\Program Files\Wireshark\tshark.exe",
    r"C:\Program Files (x86)\Wireshark\tshark.exe",
]


def find_tshark() -> Optional[str]:
    """
    Return the path to the tshark binary, or None if not found.

    Search order:
    1. PATH (via shutil.which)
    2. Common Windows installation paths
    """
    found = shutil.which("tshark")
    if found:
        return found
    for p in _WINDOWS_PATHS:
        if os.path.exists(p):
            return p
    return None


def require_tshark() -> str:
    """
    Return the tshark path or raise FileNotFoundError.

    Use this in functions that cannot proceed without tshark.
    """
    path = find_tshark()
    if not path:
        raise FileNotFoundError(
            "tshark not found. Install Wireshark and ensure tshark.exe is in PATH "
            r"or at C:\Program Files\Wireshark\tshark.exe"
        )
    return path
