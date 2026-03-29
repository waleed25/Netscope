from pathlib import Path

from fastapi import APIRouter

from shared.manifests.capability import detect, HardwareCaps
from shared.manifests.loader import get_enabled_manifests, scan_modules, load_installed

router = APIRouter()

# Paths — resolve relative to project root
_PROJECT_ROOT = Path(__file__).parent.parent
_MODULES_DIR = _PROJECT_ROOT / "modules"
_DATA_DIR = _PROJECT_ROOT / "data"


@router.get("/features")
async def get_features() -> dict[str, bool]:
    """Returns {module_name: enabled} for all known modules."""
    # Scan all manifests, then check which are enabled
    all_manifests = scan_modules(_MODULES_DIR)
    installed = load_installed(_DATA_DIR)
    result: dict[str, bool] = {}
    for m in all_manifests:
        if not installed:
            result[m.name] = True   # first run: all enabled
        else:
            result[m.name] = installed.get(m.name, {}).get("enabled", True)
    return result


@router.get("/capabilities")
async def get_capabilities() -> dict:
    """Returns detected hardware capabilities."""
    caps = detect()
    return {
        "gpu_vram_gb": caps.gpu_vram_gb,
        "ram_gb": caps.ram_gb,
        "npcap": caps.npcap,
        "libpcap": caps.libpcap,
        "os": caps.os,
        "disk_free_gb": caps.disk_free_gb,
    }
