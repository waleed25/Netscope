"""
Modbus block read engine: coalesces registers into minimal FC requests.

Groups RegisterDef instances by register_type, sorts by address, then merges
adjacent/near-adjacent registers into as few FC reads as possible.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from itertools import groupby
from typing import Any

from pymodbus.exceptions import ModbusException

from modbus.register_maps import RegisterDef
from modbus.transport import decode_registers_raw, effective_byte_order, _reg_count
from modbus.diagnostics import diagnostics_engine


# â”€â”€ ReadBlock â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class ReadBlock:
    register_type: str                        # "holding" | "input" | "coil" | "discrete"
    start_address: int
    count:         int                        # total wire span (includes any gap registers)
    regs:          list[RegisterDef] = field(default_factory=list)


# â”€â”€ Coalescing algorithm â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def coalesce(
    registers: list[RegisterDef],
    max_gap:   int = 1,
    max_block_size: int = 125,
) -> list[ReadBlock]:
    """
    Merge RegisterDef instances into minimal ReadBlocks.

    Groups by register_type, then within each group merges adjacent or
    near-adjacent (gap <= max_gap) registers into single FC read requests,
    subject to max_block_size.

    Args:
        registers:      List of RegisterDef instances.
        max_gap:        Maximum number of unused register addresses allowed
                        between two defs before a block boundary is forced.
        max_block_size: Maximum total span (in register words) for one block.

    Returns:
        List of ReadBlock â€” one FC call per block.
    """
    if not registers:
        return []

    # Sort by (register_type, address)
    sorted_regs = sorted(registers, key=lambda r: (r.register_type, r.address))

    blocks: list[ReadBlock] = []

    for rtype, group in groupby(sorted_regs, key=lambda r: r.register_type):
        group_list = list(group)

        if not group_list:
            continue

        first = group_list[0]
        block_start = first.address
        block_end   = first.address + _reg_count(first) - 1  # inclusive last register word
        block_regs  = [first]
        # Note: single registers are never split even if their word count exceeds max_block_size
        # (a float64 = 4 words cannot be split across requests)

        for reg in group_list[1:]:
            reg_end  = reg.address + _reg_count(reg) - 1
            gap      = reg.address - (block_end + 1)
            new_span = reg_end - block_start + 1

            if gap <= max_gap and new_span <= max_block_size:
                # Extend current block
                block_regs.append(reg)
                block_end = max(block_end, reg_end)
            else:
                # Flush current block
                blocks.append(ReadBlock(
                    register_type=rtype,
                    start_address=block_start,
                    count=block_end - block_start + 1,
                    regs=list(block_regs),
                ))
                # Start new block
                block_start = reg.address
                block_end   = reg_end
                block_regs  = [reg]

        # Flush last block in this group
        blocks.append(ReadBlock(
            register_type=rtype,
            start_address=block_start,
            count=block_end - block_start + 1,
            regs=list(block_regs),
        ))

    return blocks


# â”€â”€ FC dispatch tables â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_FC_NUM = {
    "holding":  3,
    "input":    4,
    "coil":     1,
    "discrete": 2,
}


def _get_fc_fn(client: Any, register_type: str):
    """Return the appropriate pymodbus client method for the given register type."""
    if register_type == "holding":
        return client.read_holding_registers
    if register_type == "input":
        return client.read_input_registers
    if register_type == "coil":
        return client.read_coils
    if register_type == "discrete":
        return client.read_discrete_inputs
    raise ValueError(f"Unknown register_type: {register_type!r}")


# â”€â”€ Block reader â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def read_blocks(
    client:              Any,
    blocks:              list[ReadBlock],
    unit_id:             int,
    session_id:          str,
    session_byte_order:  str,
    prev_values:         dict[int, int],
    address_offset:      int = 0,
) -> dict[int, dict]:
    """
    Execute one FC read per ReadBlock and decode the results.

    Returns a dict mapping Modbus register address â†’ result dict.
    The prev_values dict is updated in-place for delta tracking.

    address_offset is added to block.start_address when computing the wire
    address sent over the network (e.g. -1 for 1-based addressing).  It does
    NOT affect the fan-out offset calculation (reg.address - block.start_address),
    which must remain relative to the logical block start.
    """
    results: dict[int, dict] = {}

    for block in blocks:
        fc_fn  = _get_fc_fn(client, block.register_type)
        fc_num = _FC_NUM[block.register_type]
        wire_start = block.start_address + address_offset

        t0 = time.perf_counter()
        try:
            resp = await asyncio.wait_for(
                fc_fn(wire_start, count=block.count, device_id=unit_id),
                timeout=10.0,
            )
        except asyncio.TimeoutError as exc:
            diagnostics_engine.record(
                session_id, fc_num, wire_start,
                (time.perf_counter() - t0) * 1000,
                "timeout", None, None,
            )
            for reg in block.regs:
                results[reg.address] = {
                    "address": reg.address,
                    "name":    reg.name,
                    "unit":    reg.unit,
                    "error":   f"Timeout reading block @ {wire_start}",
                }
            continue
        except (ModbusException, Exception) as exc:
            diagnostics_engine.record(
                session_id, fc_num, wire_start,
                (time.perf_counter() - t0) * 1000,
                "exception", None, None,
            )
            for reg in block.regs:
                results[reg.address] = {
                    "address": reg.address,
                    "name":    reg.name,
                    "unit":    reg.unit,
                    "error":   str(exc),
                }
            continue

        rtt_ms = (time.perf_counter() - t0) * 1000

        if resp.isError():
            exc_code = getattr(resp, "exception_code", None)
            diagnostics_engine.record(
                session_id, fc_num, wire_start, rtt_ms,
                "exception", None, exc_code,
            )
            for reg in block.regs:
                results[reg.address] = {
                    "address": reg.address,
                    "name":    reg.name,
                    "unit":    reg.unit,
                    "error":   str(resp),
                }
            continue

        # Extract raw list: registers or bits
        if block.register_type in ("coil", "discrete"):
            raw: list[int] = [int(b) for b in resp.bits]
        else:
            raw = list(resp.registers)

        diagnostics_engine.record(
            session_id, fc_num, wire_start, rtt_ms,
            "ok", raw[:5], None,
        )

        # Decode each RegisterDef from the raw slice
        for reg in block.regs:
            offset = reg.address - block.start_address
            n      = _reg_count(reg)
            reg_slice = raw[offset: offset + n]

            if len(reg_slice) < n:
                results[reg.address] = {
                    "address": reg.address,
                    "name":    reg.name,
                    "unit":    reg.unit,
                    "error":   "Insufficient data in response",
                }
                continue

            eff_bo = effective_byte_order(session_byte_order, reg.byte_order)

            try:
                float_val, str_val = decode_registers_raw(reg_slice, reg, eff_bo)
            except Exception as exc:
                results[reg.address] = {
                    "address": reg.address,
                    "name":    reg.name,
                    "unit":    reg.unit,
                    "error":   f"Decode error: {exc}",
                }
                continue

            # Delta tracking (uint16 wrap-around aware)
            raw0 = reg_slice[0]
            prev_raw = prev_values.get(reg.address, raw0)
            diff  = (raw0 - prev_raw) & 0xFFFF
            delta = diff if diff <= 32767 else diff - 65536
            prev_values[reg.address] = raw0

            entry: dict = {
                "address":     reg.address,
                "name":        reg.name,
                "raw":         raw0,
                "delta":       delta,
                "value":       round(float_val, 4),
                "unit":        reg.unit,
                "description": reg.description,
                "access":      reg.access,
                "timestamp":   time.time(),
            }
            if str_val is not None:
                entry["str_value"] = str_val

            results[reg.address] = entry

    return results
