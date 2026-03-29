"""
Subprocess helpers — suppress console windows on Windows.

Every subprocess.run / Popen / asyncio.create_subprocess_* call should use
these helpers so that no visible cmd.exe window pops up on Windows.
"""
from __future__ import annotations
import subprocess
import sys

# On Windows, CREATE_NO_WINDOW prevents a console window from appearing
# when spawning child processes.  On other platforms this is a no-op dict.
if sys.platform == "win32":
    CREATION_FLAGS = subprocess.CREATE_NO_WINDOW
    SUBPROCESS_KWARGS: dict = {"creationflags": CREATION_FLAGS}
else:
    CREATION_FLAGS = 0
    SUBPROCESS_KWARGS: dict = {}


def run(*args, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run() wrapper that suppresses console windows on Windows."""
    kwargs.setdefault("creationflags", CREATION_FLAGS)
    return subprocess.run(*args, **kwargs)


def Popen(*args, **kwargs) -> subprocess.Popen:
    """subprocess.Popen() wrapper that suppresses console windows on Windows."""
    kwargs.setdefault("creationflags", CREATION_FLAGS)
    return subprocess.Popen(*args, **kwargs)
