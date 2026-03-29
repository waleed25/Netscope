"""
Token-Oriented Object Notation (TOON) — compact LLM-friendly packet encoding.

Instead of repeating keys for every packet (JSON), TOON declares the schema
once in a header and lists only values, saving ~40% tokens.

Example output:
    total:150 showing:10
    packets{proto,src,dst,len,info}:
    TCP,1.2.3.4:80,5.6.7.8:443,120,SYN
    DNS,192.168.1.5:1234,8.8.8.8:53,60,query example.com
"""
from __future__ import annotations


def encode_packets(packets: list[dict], total: int) -> str:
    """Encode a packet list as TOON header-based array notation."""
    header = f"total:{total} showing:{len(packets)}"
    if not packets:
        return header + "\npackets: (none)"
    fields = ("proto", "src", "dst", "len", "info")
    lines = [header, f"packets{{{','.join(fields)}}}:"]
    for p in packets:
        info = str(p.get("info", ""))
        if "," in info:          # escape embedded commas so columns stay aligned
            info = f'"{info}"'
        lines.append(",".join([
            str(p.get("proto", "")),
            str(p.get("src", "")),
            str(p.get("dst", "")),
            str(p.get("len", "")),
            info,
        ]))
    return "\n".join(lines)
