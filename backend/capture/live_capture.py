"""
Live packet capture: runs tshark as a subprocess in a background thread,
reads stdout with blocking readline() (fast on Windows), and pushes parsed
packets into an asyncio queue via call_soon_threadsafe.

This avoids the Windows ProactorEventLoop pipe-read bottleneck (~60 lines/s)
and achieves full tshark throughput (thousands of packets/s).
"""

from __future__ import annotations
import asyncio
import json
import os
import shutil
import subprocess
import threading
from typing import Optional

from utils import proc

# Protects mutations to shared global state (_is_capturing, _tshark_proc,
# _reader_thread, _packet_index) that are accessed from both the asyncio
# event loop and the background reader thread.
_state_lock = threading.Lock()

from dissector.packet_parser import parse_tshark_json

TSHARK_SEARCH_PATHS = [
    r"C:\Program Files\Wireshark\tshark.exe",
    r"C:\Program Files (x86)\Wireshark\tshark.exe",
]


def _find_tshark() -> str:
    from utils.tshark_utils import find_tshark
    found = find_tshark()
    if found:
        return found
    raise FileNotFoundError(
        "tshark not found. Install Wireshark and ensure tshark.exe is in PATH "
        "or at C:\\Program Files\\Wireshark\\tshark.exe"
    )


# ── Shared state ──────────────────────────────────────────────────────────────
_is_capturing: bool = False
_packet_index: int = 0
_active_interface: str = ""
_tshark_proc: Optional[subprocess.Popen] = None
_reader_thread: Optional[threading.Thread] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_packet_queue: asyncio.Queue  # initialised lazily per event loop


def _get_queue() -> asyncio.Queue:
    """Return (creating if needed) the queue bound to the current event loop."""
    global _packet_queue
    try:
        q = _packet_queue
        # make sure it belongs to the running loop
        return q
    except NameError:
        _packet_queue = asyncio.Queue(maxsize=10000)
        return _packet_queue


# ── Public API ────────────────────────────────────────────────────────────────

def is_capturing() -> bool:
    with _state_lock:
        return _is_capturing


def get_active_interface() -> str:
    with _state_lock:
        return _active_interface


async def get_interfaces() -> list[dict]:
    """List available network interfaces via tshark -D."""
    import re

    tshark = _find_tshark()

    # Use a thread executor instead of asyncio.create_subprocess_exec so this
    # works on both ProactorEventLoop and SelectorEventLoop (the latter raises
    # NotImplementedError for subprocess creation on Windows).
    def _run() -> bytes:
        result = proc.run(
            [tshark, "-D"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return result.stdout

    loop = asyncio.get_running_loop()
    stdout = await loop.run_in_executor(None, _run)

    interfaces = []
    for line in stdout.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(". ", 1)
        if len(parts) == 2:
            full_name = parts[1].strip()
            # Separate device path from friendly name in parentheses.
            # tshark -D lines look like:
            #   \Device\NPF_{GUID} (Wi-Fi)
            # tshark -i only accepts the device path without the
            # trailing " (friendly)" suffix.
            m = re.match(r"^(.+?)\s+\(([^)]+)\)\s*$", full_name)
            if m:
                device = m.group(1)
            else:
                device = full_name
            interfaces.append({
                "index": parts[0].strip(),
                "name": full_name,
                "device": device,
            })
    return interfaces


async def start_capture(interface: str, bpf_filter: str = "", output_path: str = "") -> None:
    global _is_capturing, _packet_index, _active_interface, _loop, _packet_queue

    with _state_lock:
        if _is_capturing:
            pass  # stop_capture called below outside the lock

    if _is_capturing:
        await stop_capture()

    with _state_lock:
        _is_capturing = True
        _packet_index = 0
        _active_interface = interface
    _loop = asyncio.get_running_loop()

    # Fresh queue each capture session
    _packet_queue = asyncio.Queue(maxsize=10000)

    _start_reader_thread(interface, bpf_filter, output_path)


async def stop_capture() -> None:
    global _is_capturing, _tshark_proc, _reader_thread

    with _state_lock:
        _is_capturing = False
        proc = _tshark_proc
        _tshark_proc = None
        thread = _reader_thread
        _reader_thread = None

    if proc:
        try:
            proc.terminate()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    if thread and thread.is_alive():
        thread.join(timeout=3.0)


async def get_packet_queue() -> asyncio.Queue:
    return _get_queue()


# ── Thread-based tshark reader ────────────────────────────────────────────────

def _start_reader_thread(interface: str, bpf_filter: str, output_path: str = "") -> None:
    global _reader_thread
    t = threading.Thread(
        target=_reader_loop,
        args=(interface, bpf_filter, output_path),
        daemon=True,
        name="tshark-reader",
    )
    _reader_thread = t
    t.start()


def _reader_loop(interface: str, bpf_filter: str, output_path: str = "") -> None:
    """
    Runs in a background thread.
    Launches tshark, reads JSON lines via blocking readline(), parses each
    packet, and schedules put_nowait on the asyncio queue via the event loop.
    """
    global _is_capturing, _tshark_proc, _packet_index  # guarded by _state_lock for writes

    tshark = _find_tshark()

    cmd = [
        tshark,
        "-i", interface,
        "-T", "ek",
        "-e", "frame.number",
        "-e", "frame.time_epoch",
        "-e", "frame.len",
        "-e", "frame.protocols",
        "-e", "ip.src",
        "-e", "ip.dst",
        "-e", "ipv6.src",
        "-e", "ipv6.dst",
        "-e", "tcp.srcport",
        "-e", "tcp.dstport",
        "-e", "tcp.flags",
        "-e", "udp.srcport",
        "-e", "udp.dstport",
        "-e", "dns.qry.name",
        "-e", "dns.resp.name",
        "-e", "http.request.method",
        "-e", "http.request.uri",
        "-e", "http.host",
        "-e", "http.response.code",
        "-e", "tls.handshake.extensions_server_name",
        "-e", "arp.src.proto_ipv4",
        "-e", "arp.dst.proto_ipv4",
        "-e", "arp.opcode",
        "-e", "icmp.type",
        # ── Modbus TCP ──────────────────────────────────────────────────────
        "-e", "mbtcp.unit_id",
        "-e", "modbus.func_code",
        "-e", "modbus.reference_num",
        "-e", "modbus.word_cnt",
        # ── DNP3 ────────────────────────────────────────────────────────────
        "-e", "dnp3.al.func",
        "-e", "dnp3.src",
        "-e", "dnp3.dst",
        "-e", "dnp3.al.obj",
        "-e", "dnp3.ctl",
        # ── OPC-UA ──────────────────────────────────────────────────────────
        "-e", "opcua.transport.type",
        "-e", "opcua.servicenodeid.numeric",
        "-e", "opcua.transport.endpoint",
        "-e", "opcua.SecurityPolicyUri",
        "-l",  # line-buffered stdout
    ]

    if output_path:
        # Ring buffer: 100 MB per file, keep 10 files (1 GB total rolling window)
        cmd += ["-w", output_path, "-b", "filesize:102400", "-b", "files:10"]

    if bpf_filter:
        cmd += ["-f", bpf_filter]

    try:
        tshark_proc = proc.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,              # unbuffered
        )
        with _state_lock:
            _tshark_proc = tshark_proc
    except Exception as e:
        print(f"[capture] failed to launch tshark: {e}")
        with _state_lock:
            _is_capturing = False
        return

    print(f"[capture] tshark started (PID {tshark_proc.pid}) on {interface}")

    queue = _get_queue()
    loop = _loop

    try:
        for raw_line in tshark_proc.stdout:
            with _state_lock:
                capturing = _is_capturing
            if not capturing:
                break

            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # tshark ek format: index lines have no "layers" key
            if "layers" not in data:
                continue

            try:
                with _state_lock:
                    idx = _packet_index
                    _packet_index += 1
                pkt = parse_tshark_json(data, idx)
            except Exception as e:
                print(f"[capture] parse error: {e}")
                continue

            # Thread-safe push into asyncio queue
            if loop and not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, pkt)
                except asyncio.QueueFull:
                    # Drop oldest to make room
                    try:
                        loop.call_soon_threadsafe(queue.get_nowait)
                        loop.call_soon_threadsafe(queue.put_nowait, pkt)
                    except Exception:
                        pass
                except Exception:
                    pass

    except Exception as e:
        with _state_lock:
            still_capturing = _is_capturing
        if still_capturing:
            print(f"[capture] reader error: {e}")
    finally:
        with _state_lock:
            _is_capturing = False
            final_count = _packet_index
        try:
            tshark_proc.terminate()
        except Exception:
            pass
        print(f"[capture] reader thread exited — {final_count} packets")
