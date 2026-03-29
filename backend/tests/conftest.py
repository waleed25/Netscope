"""
Shared pytest fixtures and path setup.
"""
import sys
import os

# Ensure the backend package root is on sys.path so all imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_packet(
    *,
    protocol="TCP",
    src_ip="10.0.0.1",
    dst_ip="10.0.0.2",
    src_port="12345",
    dst_port="80",
    length=100,
    timestamp=1_700_000_000.0,
    info="",
    details=None,
) -> dict:
    """Factory for a minimal normalized packet dict."""
    return {
        "id": 1,
        "timestamp": timestamp,
        "layers": [protocol],
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": src_port,
        "dst_port": dst_port,
        "protocol": protocol,
        "length": length,
        "info": info or f"{src_ip}:{src_port} → {dst_ip}:{dst_port}",
        "color": "green",
        "details": details or {},
    }
