"""
Modbus frame parser — pure module, no I/O, no asyncio.

Two public functions:
  parse_tcp_frame(raw, direction, ts_us) -> ParsedFrame
  parse_rtu_frame(raw, direction, ts_us) -> ParsedFrame
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ── Tables ────────────────────────────────────────────────────────────────────

EXCEPTION_NAMES: dict[int, str] = {
    0x01: "Illegal Function",
    0x02: "Illegal Data Address",
    0x03: "Illegal Data Value",
    0x04: "Server Device Failure",
    0x05: "Acknowledge",
    0x06: "Server Device Busy",
    0x08: "Memory Parity Error",
    0x0A: "Gateway Path Unavailable",
    0x0B: "Gateway Target Device Failed to Respond",
}

FC_NAMES: dict[int, str] = {
    1:  "Read Coils",
    2:  "Read Discrete Inputs",
    3:  "Read Holding Registers",
    4:  "Read Input Registers",
    5:  "Write Single Coil",
    6:  "Write Single Register",
    7:  "Read Exception Status",
    8:  "Diagnostics",
    11: "Get Comm Event Counter",
    12: "Get Comm Event Log",
    15: "Write Multiple Coils",
    16: "Write Multiple Registers",
    17: "Report Server ID",
    20: "Read File Record",
    21: "Write File Record",
    22: "Mask Write Register",
    23: "Read/Write Multiple Registers",
    43: "Read Device Identification",
}


def _fc_name(fc: int) -> str:
    return FC_NAMES.get(fc, f"FC{fc} (Unknown)")


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class MBAPHeader:
    transaction_id: int
    protocol_id: int
    length: int
    unit_id: int


@dataclass
class ParsedFrame:
    direction: Literal["tx", "rx"]
    ts_us: int
    frame_type: Literal["tcp", "rtu"]
    raw_hex: str

    mbap: MBAPHeader | None

    function_code: int
    fc_name: str
    is_exception: bool
    exception_code: int | None
    exception_name: str | None

    start_address: int | None
    quantity: int | None

    byte_count: int | None
    data_hex: str | None

    crc_valid: bool | None

    parse_error: str | None


def _error_frame(
    raw: bytes,
    direction: Literal["tx", "rx"],
    ts_us: int,
    frame_type: Literal["tcp", "rtu"],
    error: str,
) -> ParsedFrame:
    """Return a ParsedFrame with parse_error set; all other fields zeroed."""
    return ParsedFrame(
        direction=direction,
        ts_us=ts_us,
        frame_type=frame_type,
        raw_hex=raw.hex(),
        mbap=None,
        function_code=0,
        fc_name="",
        is_exception=False,
        exception_code=None,
        exception_name=None,
        start_address=None,
        quantity=None,
        byte_count=None,
        data_hex=None,
        crc_valid=None,
        parse_error=error,
    )


# ── TCP parser ────────────────────────────────────────────────────────────────

_TCP_MIN_LEN = 8  # 6 MBAP + 1 FC + at least 1 data byte


def parse_tcp_frame(raw: bytes, direction: Literal["tx", "rx"], ts_us: int) -> ParsedFrame:
    """Parse a Modbus TCP (MBAP + PDU) frame into a ParsedFrame."""
    if len(raw) < _TCP_MIN_LEN:
        return _error_frame(raw, direction, ts_us, "tcp",
                            f"truncated: {len(raw)} < {_TCP_MIN_LEN} bytes")

    tid  = (raw[0] << 8) | raw[1]
    pid  = (raw[2] << 8) | raw[3]
    plen = (raw[4] << 8) | raw[5]   # PDU length including unit_id
    uid  = raw[6]

    if pid != 0:
        return _error_frame(raw, direction, ts_us, "tcp",
                            f"protocol_id {pid:#06x} != 0x0000 (not Modbus TCP)")

    mbap = MBAPHeader(transaction_id=tid, protocol_id=pid, length=plen, unit_id=uid)

    fc_raw = raw[7]
    is_exc = bool(fc_raw & 0x80)
    fc = fc_raw & 0x7F if is_exc else fc_raw

    exc_code: int | None = None
    exc_name: str | None = None
    start_addr: int | None = None
    quantity: int | None = None
    byte_count: int | None = None
    data_hex: str | None = None
    parse_error: str | None = None

    pdu = raw[7:]   # FC byte + data

    if is_exc:
        if len(pdu) < 2:
            parse_error = "truncated: exception frame missing exception code"
        else:
            exc_code = pdu[1]
            exc_name = EXCEPTION_NAMES.get(exc_code, f"Unknown exception {exc_code:#04x}")
    else:
        # Parse request context (tx): FC + start + count
        # Only set quantity for FCs where bytes 3-4 represent a count:
        # FC1-4 (read), FC15-16 (write multiple)
        if direction == "tx" and len(pdu) >= 5:
            start_addr = (pdu[1] << 8) | pdu[2]
            if fc in (1, 2, 3, 4, 15, 16):
                quantity = (pdu[3] << 8) | pdu[4]
            # FC5, FC6, and others: pdu[3:5] is a value, not a quantity — leave quantity as None
        # Parse response context (rx): FC + byte_count + data
        elif direction == "rx" and len(pdu) >= 2 and fc in (1, 2, 3, 4):
            byte_count = pdu[1]
            data_bytes = pdu[2:2 + byte_count]
            if len(data_bytes) < byte_count:
                parse_error = (
                    f"truncated: expected {byte_count} data bytes, "
                    f"got {len(data_bytes)}"
                )
                data_hex = None   # suppress partial data when truncated
            else:
                data_hex = data_bytes.hex()

    return ParsedFrame(
        direction=direction,
        ts_us=ts_us,
        frame_type="tcp",
        raw_hex=raw.hex(),
        mbap=mbap,
        function_code=fc,
        fc_name=_fc_name(fc),
        is_exception=is_exc,
        exception_code=exc_code,
        exception_name=exc_name,
        start_address=start_addr,
        quantity=quantity,
        byte_count=byte_count,
        data_hex=data_hex,
        crc_valid=None,
        parse_error=parse_error,
    )


# ── RTU CRC ───────────────────────────────────────────────────────────────────

def _crc16(data: bytes) -> int:
    """CRC-16/IBM (polynomial 0xA001) over the given bytes. Returns uint16."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


# ── RTU parser ────────────────────────────────────────────────────────────────

_RTU_MIN_LEN = 4  # UID + FC + at least 1 data byte + 2 CRC = 5; accept 4 for edge frames


def parse_rtu_frame(raw: bytes, direction: Literal["tx", "rx"], ts_us: int) -> ParsedFrame:
    """Parse a Modbus RTU (serial) frame into a ParsedFrame."""
    if len(raw) < _RTU_MIN_LEN:
        return _error_frame(raw, direction, ts_us, "rtu",
                            f"truncated: {len(raw)} < {_RTU_MIN_LEN} bytes")

    # CRC is the last 2 bytes, little-endian
    payload   = raw[:-2]
    crc_given = (raw[-1] << 8) | raw[-2]   # little-endian: lo byte first
    crc_calc  = _crc16(payload)
    crc_ok    = crc_given == crc_calc

    uid    = raw[0]
    fc_raw = raw[1]
    is_exc = bool(fc_raw & 0x80)
    fc     = fc_raw & 0x7F if is_exc else fc_raw

    exc_code: int | None = None
    exc_name: str | None = None
    start_addr: int | None = None
    quantity: int | None = None
    byte_count: int | None = None
    data_hex: str | None = None
    parse_error: str | None = None

    if not crc_ok:
        parse_error = f"crc mismatch: expected {crc_calc:#06x}, got {crc_given:#06x}"

    pdu = raw[1:-2]   # FC + data, without UID and CRC

    if is_exc:
        if len(pdu) >= 2:
            exc_code = pdu[1]
            exc_name = EXCEPTION_NAMES.get(exc_code, f"Unknown exception {exc_code:#04x}")
    else:
        if direction == "tx" and len(pdu) >= 5:
            start_addr = (pdu[1] << 8) | pdu[2]
            if fc in (1, 2, 3, 4, 15, 16):
                quantity = (pdu[3] << 8) | pdu[4]
            # FC5, FC6: pdu[3:5] is a value, not a quantity
        elif direction == "rx" and len(pdu) >= 2 and fc in (1, 2, 3, 4):
            byte_count = pdu[1]
            data_bytes = pdu[2:2 + byte_count]
            if len(data_bytes) < byte_count:
                parse_error = (
                    f"truncated: expected {byte_count} data bytes, "
                    f"got {len(data_bytes)}"
                ) if parse_error is None else parse_error
                data_hex = None
            else:
                data_hex = data_bytes.hex()

    return ParsedFrame(
        direction=direction,
        ts_us=ts_us,
        frame_type="rtu",
        raw_hex=raw.hex(),
        mbap=None,
        function_code=fc,
        fc_name=_fc_name(fc),
        is_exception=is_exc,
        exception_code=exc_code,
        exception_name=exc_name,
        start_address=start_addr,
        quantity=quantity,
        byte_count=byte_count,
        data_hex=data_hex,
        crc_valid=crc_ok,
        parse_error=parse_error,
    )
