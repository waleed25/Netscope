#!/usr/bin/env python3
"""Standalone hardware capability detector.
Run from electron via: python capability_detector.py
Outputs JSON to stdout: {gpu_vram_gb, gpu_name, ram_gb, npcap, libpcap, os, disk_free_gb}
No external dependencies except optional psutil and torch.
"""
import json
import sys
import shutil
from pathlib import Path

def detect():
    caps = {
        "gpu_vram_gb": 0.0,
        "gpu_name": "",
        "ram_gb": 0.0,
        "npcap": False,
        "libpcap": False,
        "os": sys.platform,
        "disk_free_gb": 0.0,
        "error": None,
    }

    # RAM
    try:
        import psutil
        caps["ram_gb"] = round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception as e:
        caps["ram_gb"] = 0.0

    # GPU (CUDA via torch)
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            caps["gpu_vram_gb"] = round(props.total_memory / (1024 ** 3), 1)
            caps["gpu_name"] = props.name
    except Exception:
        pass

    # Npcap (Windows)
    if sys.platform == "win32":
        caps["npcap"] = Path(r"C:\Windows\System32\Npcap\npcap.sys").exists()

    # libpcap (Linux/Mac)
    if sys.platform != "win32":
        caps["libpcap"] = shutil.which("tcpdump") is not None

    # Disk (cwd drive)
    try:
        import psutil
        usage = psutil.disk_usage(str(Path.home().anchor))
        caps["disk_free_gb"] = round(usage.free / (1024 ** 3), 1)
    except Exception:
        pass

    return caps

if __name__ == "__main__":
    result = detect()
    print(json.dumps(result))
