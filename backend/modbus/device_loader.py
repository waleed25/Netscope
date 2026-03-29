"""
Device list loader.

Parses a CSV or Excel file containing a list of Modbus devices, matches each
row to a predefined register map, and returns a list of DeviceConfig objects.

Expected CSV/Excel columns (names are case-insensitive, order flexible):
  ip            — device IP address              (required)
  unit_id       — Modbus unit / slave ID (1-247)  (optional, default 1)
  port          — TCP port                        (optional, default 502)
  device_type   — type keyword, e.g. "inverter"   (optional)
  device_name   — brand/model, e.g. "SMA Sunny Boy" (optional)
  description   — free text                       (optional)

The loader normalises column names (strip, lower, replace spaces/_) so that
"Device Name", "device_name", "Device-Name" all map to "device_name".

Example CSV:
  ip,device_type,device_name,unit_id
  192.168.1.10,inverter,SMA Tripower 25000TL,1
  192.168.1.11,inverter,Fronius Symo 15.0-3,1
  192.168.1.20,meter,Carlo Gavazzi EM24,1
  192.168.1.30,battery,BYD HVM 11.0,1
"""

from __future__ import annotations
import csv
import io
from dataclasses import dataclass, field
from typing import Any

from modbus.register_maps import RegisterDef, lookup, DEFAULT_MAP


@dataclass
class DeviceConfig:
    ip:           str
    port:         int
    unit_id:      int
    device_type:  str
    device_name:  str
    description:  str
    map_key:      str               # matched register-map keyword
    registers:    list[RegisterDef]
    raw_row:      dict = field(default_factory=dict, repr=False)


def _norm(col: str) -> str:
    """Normalise a column header to a consistent key."""
    return col.strip().lower().replace(" ", "_").replace("-", "_")


_COL_ALIASES: dict[str, str] = {
    "ip_address":    "ip",
    "address":       "ip",
    "host":          "ip",
    "ipaddress":     "ip",
    "slave_id":      "unit_id",
    "slave":         "unit_id",
    "node":          "unit_id",
    "nodeid":        "unit_id",
    "node_id":       "unit_id",
    "unit":          "unit_id",
    "name":          "device_name",
    "model":         "device_name",
    "brand":         "device_name",
    "type":          "device_type",
    "category":      "device_type",
    "desc":          "description",
    "notes":         "description",
    "comment":       "description",
}


def _resolve(row: dict[str, Any]) -> dict[str, str]:
    """Normalise a CSV row dict to a canonical-key dict."""
    out: dict[str, str] = {}
    for raw_key, val in row.items():
        key = _norm(raw_key)
        key = _COL_ALIASES.get(key, key)
        out[key] = str(val).strip() if val is not None else ""
    return out


def _parse_rows(rows: list[dict[str, Any]]) -> list[DeviceConfig]:
    devices: list[DeviceConfig] = []
    for i, row in enumerate(rows):
        r = _resolve(row)
        ip = r.get("ip", "").strip()
        if not ip or ip.lower() in ("", "none", "nan"):
            continue  # skip blank rows

        try:
            port = int(r.get("port", "502") or "502")
        except ValueError:
            port = 502

        try:
            unit_id = int(r.get("unit_id", "1") or "1")
        except ValueError:
            unit_id = 1

        device_type = r.get("device_type", "")
        device_name = r.get("device_name", "")
        description = r.get("description", "")

        map_key, registers = lookup(device_type, device_name)

        devices.append(DeviceConfig(
            ip=ip,
            port=port,
            unit_id=unit_id,
            device_type=device_type,
            device_name=device_name,
            description=description,
            map_key=map_key,
            registers=registers,
            raw_row=dict(row),
        ))

    return devices


def load_csv(content: str | bytes) -> list[DeviceConfig]:
    """Parse a CSV string or bytes into a list of DeviceConfig."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    return _parse_rows(rows)


def load_excel(content: bytes) -> list[DeviceConfig]:
    """Parse an Excel (.xlsx / .xls) file bytes into a list of DeviceConfig."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    # First row is header
    headers = [str(c) if c is not None else "" for c in next(rows_iter, [])]
    rows: list[dict] = []
    for row in rows_iter:
        rows.append({headers[i]: row[i] for i in range(min(len(headers), len(row)))})
    wb.close()
    return _parse_rows(rows)


def load_file(filename: str, content: bytes) -> list[DeviceConfig]:
    """Dispatch to CSV or Excel loader based on file extension."""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in ("xlsx", "xlsm", "xls"):
        return load_excel(content)
    else:
        return load_csv(content)


def devices_to_dict(devices: list[DeviceConfig]) -> list[dict]:
    """Return a JSON-serialisable summary list."""
    return [
        {
            "ip":          d.ip,
            "port":        d.port,
            "unit_id":     d.unit_id,
            "device_type": d.device_type,
            "device_name": d.device_name,
            "description": d.description,
            "map_key":     d.map_key,
            "register_count": len(d.registers),
        }
        for d in devices
    ]
