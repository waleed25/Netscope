"""
TOON — Token-Oriented Object Notation.

Reduces token consumption by 30-60% vs JSON by eliminating structural
punctuation (braces, brackets, quotes) and using header-based array notation.

Format examples
---------------
Packet table:
  PACKETS[3]
  frame proto src dst len
  1 TCP 192.168.1.1:4432 10.0.0.1:80 64
  2 UDP 192.168.1.1:53 8.8.8.8:53 42
  3 TCP 192.168.1.1:4432 10.0.0.1:80 128

Stats:
  MODBUS_STATS
  total_packets 142
  exception_count 7
  unique_devices 3

Expert info:
  EXPERT_INFO[4]
  severity group protocol summary count
  Error Sequence TCP Previous segment not captured 2
  Warn Malformed HTTP Chunked data size mismatch 1
"""

from __future__ import annotations
from typing import Any


def _val(v: Any, max_len: int = 40) -> str:
    """Stringify a value, replacing whitespace and truncating."""
    s = "" if v is None else str(v)
    # Replace internal whitespace so each cell stays one token
    s = s.replace("\n", "\\n").replace("\r", "").replace("\t", " ")
    if len(s) > max_len:
        s = s[:max_len - 1] + "…"
    return s or "-"


def to_toon(records: list[dict], title: str, max_rows: int = 200) -> str:
    """
    Convert a list of dicts to a TOON table block.

    Output:
      TITLE[n]
      col1 col2 col3
      v1   v2   v3
      ...
    """
    if not records:
        return f"{title}[0]\n(empty)"

    total = len(records)
    rows = records[:max_rows]
    cols = list(rows[0].keys())

    lines = [f"{title}[{total}]", " ".join(cols)]
    for row in rows:
        lines.append(" ".join(_val(row.get(c)) for c in cols))

    if total > max_rows:
        lines.append(f"... ({total - max_rows} rows omitted)")

    return "\n".join(lines)


def stats_to_toon(stats: dict, title: str) -> str:
    """
    Convert a flat stats dict to TOON key-value block.

    Output:
      TITLE
      key1 value1
      key2 value2
    """
    if not stats:
        return f"{title}\n(empty)"

    lines = [title]
    for k, v in stats.items():
        if isinstance(v, dict):
            # Inline nested dict as "key: k1=v1,k2=v2"
            inner = ",".join(f"{ik}={_val(iv, 20)}" for ik, iv in list(v.items())[:10])
            lines.append(f"{k} {inner[:80]}")
        elif isinstance(v, (list, tuple)):
            lines.append(f"{k} [{','.join(_val(x, 20) for x in list(v)[:10])}]")
        else:
            lines.append(f"{k} {_val(v, 60)}")
    return "\n".join(lines)


# ── Expert info parser ────────────────────────────────────────────────────────

_SEVERITY_MARKERS = {
    "Errors":   "Error",
    "Warnings": "Warn",
    "Notes":    "Note",
    "Chats":    "Chat",
}


def expert_lines_to_toon(lines: list[str], title: str = "EXPERT_INFO") -> str:
    """
    Parse tshark -z expert output into a TOON table.

    tshark expert format (after the header):
      Group      Severity  Protocol  Summary
      Sequence   Error     TCP       Previous segment(s) not captured
        192.168.1.1 → 10.0.0.1 (count: 2)
      ...
      === 1 expert info subtree ===
    """
    entries: list[dict] = []
    current_severity = "Info"
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        # Section header like "Errors (N)" or "Warnings (N)"
        for marker, sev in _SEVERITY_MARKERS.items():
            if line.strip().startswith(marker):
                current_severity = sev
                break

        # Entry lines: "  Group  Severity  Protocol  Summary"
        # tshark -z expert -q output looks like:
        # "  Malformed  Error  HTTP  Chunked data problem"
        stripped = line.strip()
        if stripped and not stripped.startswith("===") and not stripped.startswith("Errors") \
                and not stripped.startswith("Warnings") and not stripped.startswith("Notes") \
                and not stripped.startswith("Chats") and not stripped.startswith("Group"):
            # Try to detect count from next line ("  192.168.x.x (count: N)")
            count = 1
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if "count:" in next_line:
                    try:
                        count = int(next_line.split("count:")[-1].strip().rstrip(")"))
                    except ValueError:
                        pass

            parts = stripped.split(None, 3)
            if len(parts) >= 2:
                group = parts[0] if len(parts) >= 1 else "?"
                # The severity in the line may differ from section header — use line value
                sev_in_line = parts[1] if len(parts) >= 2 else current_severity
                protocol = parts[2] if len(parts) >= 3 else "?"
                summary = parts[3] if len(parts) >= 4 else stripped
                entries.append({
                    "severity": sev_in_line,
                    "group":    group,
                    "protocol": protocol,
                    "summary":  summary[:60],
                    "count":    count,
                })
        i += 1

    if not entries:
        return f"{title}[0]\n(no expert info — capture may be too short or have no anomalies)"

    return to_toon(entries, title)


# ── Protocol-specific field parsers ──────────────────────────────────────────

def tshark_fields_to_toon(
    raw: str,
    columns: list[str],
    title: str = "TSHARK_FIELDS",
    separator: str = "\t",
    max_rows: int = 200,
) -> str:
    """
    Generic converter: parse any ``tshark -T fields`` output into TOON.

    *columns* defines the header names (must match the number of ``-e``
    flags used in the tshark command).  Each non-empty line of *raw* is
    split by *separator* and mapped to the column names.
    """
    if not raw or not raw.strip():
        return f"{title}[0]\n(empty)"

    records: list[dict] = []
    for line in raw.strip().splitlines():
        parts = line.split(separator)
        if len(parts) < len(columns):
            parts.extend([""] * (len(columns) - len(parts)))
        row = {col: _val(parts[i], 50) for i, col in enumerate(columns)}
        records.append(row)
        if len(records) >= max_rows:
            break

    return to_toon(records, title, max_rows=max_rows)


def modbus_fields_to_toon(raw_tsv: str, title: str = "MODBUS_PACKETS") -> str:
    """
    Parse ``tshark -T fields`` TSV output for Modbus packets.

    Expected tshark invocation::

        tshark -r capture.pcap -Y modbus -T fields -E separator=\\t \\
            -e frame.number -e frame.time_relative \\
            -e modbus.func_code -e modbus.unit_id \\
            -e ip.src -e ip.dst \\
            -e modbus.exception_code

    Returns a TOON table with columns: ``frame time fc unit src dst exc``
    """
    columns = ["frame", "time", "fc", "unit", "src", "dst", "exc"]
    return tshark_fields_to_toon(raw_tsv, columns, title, separator="\t")


def dnp3_fields_to_toon(raw_csv: str, title: str = "DNP3_PACKETS") -> str:
    """
    Parse ``tshark -T fields`` CSV output for DNP3 packets.

    Expected tshark invocation::

        tshark -r capture.pcap -Y dnp3 -T fields -E separator=, \\
            -e frame.number -e frame.time_relative \\
            -e ip.src -e ip.dst \\
            -e dnp3.src -e dnp3.dst \\
            -e dnp3.al.func -e dnp3.al.obj

    Returns a TOON table with columns:
    ``frame time ip_src ip_dst dnp3_src dnp3_dst func obj``
    """
    columns = ["frame", "time", "ip_src", "ip_dst", "dnp3_src", "dnp3_dst", "func", "obj"]
    return tshark_fields_to_toon(raw_csv, columns, title, separator=",")
