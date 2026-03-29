"""
Modbus TCP Device Scanner.

Scans a network range for Modbus TCP devices by:
  1. TCP port probing on port 502 (and optionally others)
  2. Sending a valid Modbus read-holding-registers request (FC3) to unit IDs
     1-10 (configurable) and checking for a valid response (not exception).
  3. For each responding device, reading a set of identification registers to
     guess the device type.

Returns a list of ScanResult dicts.

Usage:
  results = await scan_network("192.168.1.0/24", timeout=1.0, max_concurrent=50)
  results = await scan_hosts(["192.168.1.10", "192.168.1.11"], timeout=2.0)
"""

from __future__ import annotations
import asyncio
import ipaddress
import time
from typing import Any

from pymodbus.client import AsyncModbusTcpClient


# ── Identification register heuristics ───────────────────────────────────────
# Maps (port, unit_id) → try to read these addresses and infer device type.

_PROBE_ADDRESSES = [0, 1, 40001, 40069, 40070, 30051, 10100, 500]
_PROBE_FC3_ADDR  = 0    # minimal FC3 read: address 0, count 1
_MODBUS_PORTS    = [502, 503, 5020]


async def _probe_host(
    host: str,
    port: int = 502,
    unit_ids: list[int] | None = None,
    timeout: float = 2.0,
) -> dict | None:
    """
    Try to connect and read FC3 HR 0 count 1.
    Returns a result dict on success, None on failure.
    """
    if unit_ids is None:
        unit_ids = list(range(1, 5))

    client = AsyncModbusTcpClient(host, port=port)
    try:
        connected = await asyncio.wait_for(client.connect(), timeout=timeout)
        if not connected:
            return None

        for uid in unit_ids:
            try:
                resp = await asyncio.wait_for(
                    client.read_holding_registers(
                        _PROBE_FC3_ADDR, count=2, device_id=uid
                    ),
                    timeout=timeout,
                )
                if not resp.isError():
                    # Try to read a few more registers for identification
                    extra: dict[int, int] = {}
                    for addr in [0, 1, 2, 3]:
                        try:
                            r2 = await asyncio.wait_for(
                                client.read_holding_registers(addr, count=1, device_id=uid),
                                timeout=timeout,
                            )
                            if not r2.isError():
                                extra[addr] = r2.registers[0]
                        except Exception:
                            pass

                    return {
                        "host":    host,
                        "port":    port,
                        "unit_id": uid,
                        "regs":    {str(a): v for a, v in extra.items()},
                        "latency_ms": 0,
                    }
            except (asyncio.TimeoutError, Exception):
                continue
    except (asyncio.TimeoutError, Exception):
        pass
    finally:
        try:
            client.close()
        except Exception:
            pass
    return None


def _guess_device_type(result: dict) -> str:
    """Heuristic: look at port and register values to guess device type."""
    port = result.get("port", 502)
    regs = result.get("regs", {})
    # Very rough heuristics
    if port == 5020:
        return "simulator"
    r0 = regs.get("0", 0)
    r1 = regs.get("1", 0)
    # Many inverters expose status 4 (MPPT) at register 0 or 1
    if r0 in (4, 307):
        return "inverter (probable)"
    if r0 == 0 and 0 < r1 < 65535:
        return "unknown device"
    return "unknown"


async def scan_hosts(
    hosts: list[str],
    *,
    ports: list[int] | None = None,
    unit_ids: list[int] | None = None,
    timeout: float = 2.0,
    max_concurrent: int = 20,
) -> list[dict]:
    """Scan a specific list of hosts."""
    if ports is None:
        ports = [502]
    if unit_ids is None:
        unit_ids = list(range(1, 5))

    sem = asyncio.Semaphore(max_concurrent)

    async def _probe_guarded(host: str, port: int) -> dict | None:
        async with sem:
            result = await _probe_host(host, port, unit_ids, timeout)
            if result:
                result["device_type_guess"] = _guess_device_type(result)
                result["scanned_at"] = time.time()
            return result

    tasks = [_probe_guarded(h, p) for h in hosts for p in ports]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in raw if isinstance(r, dict)]


async def scan_network(
    cidr: str,
    *,
    ports: list[int] | None = None,
    unit_ids: list[int] | None = None,
    timeout: float = 1.0,
    max_concurrent: int = 50,
) -> list[dict]:
    """
    Scan an entire subnet (e.g. '192.168.1.0/24').
    Skips network and broadcast addresses.
    """
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError as e:
        raise ValueError(f"Invalid CIDR: {cidr}") from e

    # Limit to /16 to avoid ridiculous scans
    if net.num_addresses > 65536:
        raise ValueError("Scan range too large — maximum /16 (65536 hosts)")

    hosts = [str(h) for h in net.hosts()]
    return await scan_hosts(
        hosts,
        ports=ports,
        unit_ids=unit_ids,
        timeout=timeout,
        max_concurrent=max_concurrent,
    )


async def scan_range(
    start_ip: str,
    end_ip: str,
    *,
    ports: list[int] | None = None,
    unit_ids: list[int] | None = None,
    timeout: float = 1.0,
    max_concurrent: int = 50,
) -> list[dict]:
    """Scan from start_ip to end_ip inclusive."""
    try:
        start = ipaddress.ip_address(start_ip)
        end   = ipaddress.ip_address(end_ip)
    except ValueError as e:
        raise ValueError(str(e)) from e

    if int(end) - int(start) > 65535:
        raise ValueError("Range too large — maximum 65536 hosts")

    hosts = [str(ipaddress.ip_address(i)) for i in range(int(start), int(end) + 1)]
    return await scan_hosts(
        hosts,
        ports=ports,
        unit_ids=unit_ids,
        timeout=timeout,
        max_concurrent=max_concurrent,
    )
