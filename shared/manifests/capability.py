import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HardwareCaps:
    gpu_vram_gb: float = 0.0
    ram_gb: float = 0.0
    npcap: bool = False
    libpcap: bool = False
    os: str = sys.platform
    disk_free_gb: float = 0.0


def detect() -> HardwareCaps:
    caps = HardwareCaps()

    # RAM
    try:
        import psutil
        caps.ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        pass

    # GPU (CUDA via torch)
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            caps.gpu_vram_gb = props.total_memory / (1024 ** 3)
    except Exception:
        pass

    # Npcap (Windows)
    if sys.platform == "win32":
        caps.npcap = Path(r"C:\Windows\System32\Npcap\npcap.sys").exists()

    # libpcap (Linux/Mac)
    if sys.platform != "win32":
        caps.libpcap = shutil.which("tcpdump") is not None

    # Disk free (cwd drive)
    try:
        import psutil
        usage = psutil.disk_usage(Path.cwd().anchor)
        caps.disk_free_gb = usage.free / (1024 ** 3)
    except Exception:
        pass

    return caps


def satisfies(caps: HardwareCaps, req) -> bool:
    """Check if HardwareCaps satisfies a HardwareRequires spec."""
    if caps.ram_gb > 0 and caps.ram_gb < req.ram_gb_min:
        return False
    if req.needs_npcap and not caps.npcap:
        return False
    if req.needs_libpcap and not caps.libpcap:
        return False
    if caps.disk_free_gb > 0 and caps.disk_free_gb < req.disk_gb_min:
        return False
    # If module requires GPU and device has no VRAM, unsatisfied
    if "cpu" not in req.gpu_modes and caps.gpu_vram_gb == 0:
        return False
    return True
