"""
SunSpec Client â€” probes Modbus TCP devices for SunSpec model blocks.

SunSpec is a standard for solar/energy device data exchange over Modbus.
Devices store a "SunS" marker at one of three well-known base addresses,
followed by a sequence of model blocks terminated by a sentinel DID=0xFFFF.
"""

from __future__ import annotations
import struct
from pymodbus.client import AsyncModbusTcpClient

MAX_REGS_PER_REQUEST = 125


async def _read_registers_chunked(client, address: int, count: int, unit_id: int) -> list[int]:
    """Read `count` registers starting at `address`, chunking at 125 per request."""
    result = []
    offset = 0
    while offset < count:
        chunk_size = min(MAX_REGS_PER_REQUEST, count - offset)
        resp = await client.read_holding_registers(
            address=address + offset, count=chunk_size, device_id=unit_id
        )
        if resp.isError():
            raise RuntimeError(f"Modbus error reading {address + offset}+{chunk_size}")
        result.extend(resp.registers)
        offset += chunk_size
    return result


class SunSpecClient:
    BASE_ADDRESSES = [40000, 50000, 0]
    SUNS_MARKER = [0x5375, 0x6E53]  # "SunS"
    SENTINEL_DID = 0xFFFF

    # Known model names by DID
    MODEL_NAMES = {
        1: "Common",
        101: "Inverter (Single Phase)",
        103: "Inverter (Three Phase)",
        201: "Meter (Single Phase)",
        202: "Meter (Split Phase)",
        203: "Meter (Three Phase Wye)",
        204: "Meter (Three Phase Delta)",
    }

    @staticmethod
    async def discover(host: str, port: int = 502, unit_id: int = 1) -> dict:
        """
        Probe device for SunSpec marker and walk model blocks.

        Returns:
        {
            "found": bool,
            "base_address": int | None,
            "models": [
                {
                    "did": int,
                    "name": str,
                    "base_addr": int,
                    "length": int,
                    "registers": {}   # raw register values, keyed by offset (int)
                },
                ...
            ]
        }
        On connection error or no marker found:
            {"found": False, "base_address": None, "models": []}
        """
        empty = {"found": False, "base_address": None, "models": []}

        client = None
        try:
            client = AsyncModbusTcpClient(host, port=port, timeout=5)
            await client.connect()

            found_base = None
            for base_address in SunSpecClient.BASE_ADDRESSES:
                resp = await client.read_holding_registers(
                    address=base_address, count=2, device_id=unit_id
                )
                if resp.isError():
                    continue
                if list(resp.registers) == SunSpecClient.SUNS_MARKER:
                    found_base = base_address
                    break

            if found_base is None:
                return empty

            # Walk model blocks starting after the 2-register marker
            models = []
            addr = found_base + 2

            while True:
                # Read DID + Length (2 registers)
                hdr = await client.read_holding_registers(
                    address=addr, count=2, device_id=unit_id
                )
                if hdr.isError():
                    break

                did = hdr.registers[0]
                length = hdr.registers[1]

                # Sentinel: end of model list
                if did == SunSpecClient.SENTINEL_DID:
                    break

                # Null model: skip
                if length == 0:
                    addr += 2
                    continue

                # Read model data registers (chunked to respect 125-register PDU limit)
                registers: dict[int, int] = {}
                try:
                    raw_regs = await _read_registers_chunked(client, addr + 2, length, unit_id)
                    registers = {i: raw_regs[i] for i in range(len(raw_regs))}
                except RuntimeError:
                    pass

                models.append(
                    {
                        "did": did,
                        "name": SunSpecClient.MODEL_NAMES.get(did, f"Model {did}"),
                        "base_addr": addr,
                        "length": length,
                        "registers": registers,
                    }
                )

                addr += 2 + length

            return {
                "found": True,
                "base_address": found_base,
                "models": models,
            }

        except Exception as e:
            print(f"SunSpec discover error: {e}")
            return empty

        finally:
            if client is not None:
                client.close()


def apply_scale_factors(
    registers: dict[int, int],
    model_registers: list[tuple[int, str]],
) -> dict[str, dict]:
    """
    Given raw register values and a list of (offset, name) pairs,
    apply *_SF scale factors to produce scaled values.

    - For each name ending in '_SF': it's a scale factor (signed int16 exponent).
    - For other registers: if a corresponding <name>_SF register exists, apply it.
    - Returns: {name: {"raw": int, "scaled": float, "sf_applied": bool}}

    Signed int16 conversion uses struct pack/unpack to handle two's-complement.
    """
    # Build offsetâ†’name and nameâ†’offset maps
    offset_to_name: dict[int, str] = {offset: name for offset, name in model_registers}
    name_to_offset: dict[str, int] = {name: offset for offset, name in model_registers}

    result: dict[str, dict] = {}

    for offset, name in model_registers:
        raw = registers.get(offset, 0)

        if name.endswith("_SF"):
            # Scale factor register: store as-is (signed int16)
            signed = struct.unpack(">h", struct.pack(">H", raw & 0xFFFF))[0]
            result[name] = {"raw": raw, "scaled": float(signed), "sf_applied": False}
            continue

        # Check if there is a corresponding SF register
        sf_name = f"{name}_SF"
        sf_applied = False
        scaled = float(raw)

        if sf_name in name_to_offset:
            sf_offset = name_to_offset[sf_name]
            sf_raw = registers.get(sf_offset, 0)
            # Convert SF raw uint16 â†’ signed int16
            sf = struct.unpack(">h", struct.pack(">H", sf_raw & 0xFFFF))[0]
            scaled = raw * (10 ** sf)
            sf_applied = True

        result[name] = {"raw": raw, "scaled": scaled, "sf_applied": sf_applied}

    return result
