"""
Read and parse .pcap / .pcapng files using scapy.
Returns a list of normalized packet dicts.
"""

from __future__ import annotations
import asyncio
from pathlib import Path
from typing import AsyncGenerator

from dissector.packet_parser import parse_scapy_packet


async def read_pcap(file_path: str) -> AsyncGenerator[dict, None]:
    """
    Async generator that yields parsed packet dicts from a pcap file.
    Uses asyncio.to_thread to avoid blocking the event loop.
    """
    packets = await asyncio.to_thread(_load_pcap_sync, file_path)
    for pkt in packets:
        yield pkt


def _load_pcap_sync(file_path: str) -> list[dict]:
    """Synchronously load and parse a pcap file. Runs in a thread."""
    from scapy.utils import rdpcap
    try:
        raw_packets = rdpcap(file_path)
    except Exception as e:
        raise ValueError(f"Failed to read pcap file: {e}")

    results = []
    for i, pkt in enumerate(raw_packets):
        try:
            parsed = parse_scapy_packet(pkt, i)
            results.append(parsed)
        except Exception as e:
            print(f"[pcap] error parsing packet {i}: {e}")

    return results


async def read_pcap_list(file_path: str) -> list[dict]:
    """Return all parsed packets as a list."""
    return await asyncio.to_thread(_load_pcap_sync, file_path)
