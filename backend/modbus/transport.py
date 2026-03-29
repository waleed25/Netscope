"""
Modbus transport abstraction: client construction and register decoding.

NOTE: pymodbus 3.6+ removed BinaryPayloadDecoder and Endian from pymodbus.constants.
Decoding is done manually via the struct module.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Literal

from pymodbus.client import AsyncModbusTcpClient, AsyncModbusSerialClient
from pymodbus.framer import FramerType

from modbus.register_maps import RegisterDef


# ── Register width helper ──────────────────────────────────────────────────────

def _reg_count(reg_def: RegisterDef) -> int:
    """Number of Modbus register words consumed by this definition."""
    dt = reg_def.data_type
    if dt in ("uint32", "int32", "float32"):
        return 2
    if dt in ("float64", "int64", "uint64"):
        return 4
    if dt == "string":
        # string_length=0 means a single-register (2-byte) string;
        # always specify explicitly for longer strings
        return max(1, math.ceil(reg_def.string_length / 2)) if reg_def.string_length > 0 else 1
    # uint16, int16, boolean, bcd → 1
    return 1


# ── Transport config ───────────────────────────────────────────────────────────

@dataclass
class TransportConfig:
    transport:   Literal["tcp", "rtu", "ascii"] = "tcp"
    host:        str   = "127.0.0.1"
    port:        int   = 502
    serial_port: str   = ""        # "COM3" or "/dev/ttyUSB0"
    baudrate:    int   = 9600
    bytesize:    int   = 8
    parity:      str   = "N"       # "N", "E", "O"
    stopbits:    int   = 1
    timeout:     float = 3.0


def build_client(cfg: TransportConfig):
    """Construct the appropriate pymodbus async client for the given transport."""
    if cfg.transport == "tcp":
        return AsyncModbusTcpClient(
            cfg.host,
            port=cfg.port,
            timeout=cfg.timeout,
        )
    elif cfg.transport == "rtu":
        return AsyncModbusSerialClient(
            port=cfg.serial_port,
            framer=FramerType.RTU,
            baudrate=cfg.baudrate,
            bytesize=cfg.bytesize,
            parity=cfg.parity,
            stopbits=cfg.stopbits,
            timeout=cfg.timeout,
        )
    elif cfg.transport == "ascii":
        return AsyncModbusSerialClient(
            port=cfg.serial_port,
            framer=FramerType.ASCII,
            baudrate=cfg.baudrate,
            bytesize=cfg.bytesize,
            parity=cfg.parity,
            stopbits=cfg.stopbits,
            timeout=cfg.timeout,
        )
    else:
        raise ValueError(f"Unknown transport: {cfg.transport!r}")


# ── Byte order helpers ─────────────────────────────────────────────────────────

def effective_byte_order(session_default: str, reg_override: str | None) -> str:
    """Return reg_override if set, else fall back to session_default."""
    return reg_override if reg_override is not None else session_default



def _pack_words(words: list[int], byte_order: str) -> bytes:
    """
    Pack a list of uint16 register words into a contiguous byte buffer
    according to the given byte-order code.

    word_order:
      "ABCD" / "BADC": words in big-endian order (word[0] is most significant)
      "CDAB" / "DCBA": words in little-endian order (word[0] is least significant)

    byte_order within each word:
      "ABCD" / "CDAB": each uint16 packed big-endian (>H)
      "BADC" / "DCBA": each uint16 packed little-endian (<H)
    """
    # Determine byte endianness per word
    if byte_order in ("ABCD", "CDAB"):
        pack_char = ">"   # big-endian bytes within each word
    else:  # BADC, DCBA
        pack_char = "<"   # little-endian bytes within each word

    # Determine word order
    if byte_order in ("CDAB", "DCBA"):
        ordered_words = list(reversed(words))
    else:
        ordered_words = words

    buf = b"".join(struct.pack(f"{pack_char}H", w) for w in ordered_words)
    return buf


# ── Register decoding ──────────────────────────────────────────────────────────

def decode_registers_raw(
    regs: list[int],
    reg_def: RegisterDef,
    byte_order: str,
) -> tuple[float, str | None]:
    """
    Decode raw register words into (float_value, string_value_or_None).

    For string type: returns (0.0, decoded_string).
    For all others: returns (float_value, None).
    """
    dt = reg_def.data_type
    scale = reg_def.scale or 1.0

    if dt == "uint16":
        return float(regs[0]) / scale, None

    if dt == "int16":
        raw = regs[0] if regs[0] < 32768 else regs[0] - 65536
        return float(raw) / scale, None

    if dt in ("uint32", "int32", "float32"):
        if len(regs) < 2:
            return 0.0, None
        buf = _pack_words(regs[:2], byte_order)
        if dt == "uint32":
            val = struct.unpack(">I", buf)[0]
            return float(val) / scale, None
        if dt == "int32":
            val = struct.unpack(">i", buf)[0]
            return float(val) / scale, None
        if dt == "float32":
            val = struct.unpack(">f", buf)[0]
            return float(val) / scale, None

    if dt in ("uint64", "int64", "float64"):
        if len(regs) < 4:
            return 0.0, None
        buf = _pack_words(regs[:4], byte_order)
        if dt == "uint64":
            val = struct.unpack(">Q", buf)[0]
            return float(val) / scale, None
        if dt == "int64":
            val = struct.unpack(">q", buf)[0]
            return float(val) / scale, None
        if dt == "float64":
            val = struct.unpack(">d", buf)[0]
            return float(val) / scale, None

    if dt == "boolean":
        bit = bool((regs[0] >> reg_def.bit_position) & 1)
        return (1.0 if bit else 0.0), None

    if dt == "bcd":
        w = regs[0]
        val = (
            ((w >> 12) & 0xF) * 1000
            + ((w >> 8) & 0xF) * 100
            + ((w >> 4) & 0xF) * 10
            + (w & 0xF)
        )
        return float(val) / scale, None

    if dt == "string":
        # Use reg_def.string_length if set, otherwise decode entire available buffer
        max_chars = reg_def.string_length if reg_def.string_length > 0 else len(regs) * 2
        n_words = max(1, math.ceil(max_chars / 2))
        raw_bytes = b""
        for w in regs[:n_words]:
            raw_bytes += struct.pack(">H", w)
        decoded = raw_bytes.decode("ascii", errors="replace").rstrip("\x00")
        if reg_def.string_length > 0:
            decoded = decoded[: reg_def.string_length]
        return 0.0, decoded

    # Default fallback
    return float(regs[0]) / scale, None


def decode_registers(
    regs: list[int],
    reg_def: RegisterDef,
    byte_order: str,
) -> float:
    """Convenience wrapper — returns only the float value."""
    val, _ = decode_registers_raw(regs, reg_def, byte_order)
    return val
