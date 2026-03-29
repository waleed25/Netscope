"""
Modbus TCP ICS Traffic Simulator.

Simulates a realistic industrial Modbus TCP slave (server) with:
- Holding registers representing ICS sensor/actuator values
- Sinusoidal + noise register updates every 2 seconds
- Anomalous traffic generation: unexpected write attempts and out-of-range
  address reads (triggers Modbus exception responses)

Usage:
  python simulate_modbus.py --mode server          # run slave only
  python simulate_modbus.py --mode client          # run client only (connect to :5020)
  python simulate_modbus.py --mode both            # server + client together
  python simulate_modbus.py --mode both --port 5020 --duration 60 --anomaly-rate 0.1

Dependencies:
  pip install pymodbus>=3.0
"""

from __future__ import annotations
import argparse
import asyncio
import logging
import math
import random
import time
from typing import Optional

log = logging.getLogger("sim_modbus")

# ── Register map ──────────────────────────────────────────────────────────────
#
# Address  Description            Normal range    Units
# 0        DC voltage             3300–3400       (×0.1 V) → 330–340 V
# 1        AC current             100–150         (×0.1 A) → 10–15 A
# 2        Power factor           950–1000        (×0.001) → 0.95–1.00
# 3        Fault register         0 (normal)      bit flags
# 4        Mode register          0=auto, 1=manual
# 5        Temperature            200–300         (×0.1 °C) → 20–30 °C
# 6        Output power           0–5000          W
# 7        Frequency              499–501         (×0.1 Hz) → 49.9–50.1 Hz
# 8        Runtime hours          0–65535         hours
# 9        Status word            0x0001 (running)

INITIAL_REGISTERS = [
    3350,   # 0: DC voltage
    125,    # 1: AC current
    985,    # 2: Power factor
    0,      # 3: Fault register (0 = no fault)
    0,      # 4: Mode (0 = auto)
    250,    # 5: Temperature
    2500,   # 6: Output power
    500,    # 7: Frequency
    0,      # 8: Runtime hours
    0x0001, # 9: Status word (running)
]


class RegisterStore:
    """Thread-safe register store with realistic dynamic updates."""

    def __init__(self):
        self._regs = list(INITIAL_REGISTERS)
        self._lock = asyncio.Lock()
        self._start = time.monotonic()

    async def update(self):
        """Simulate register updates with sinusoidal drift + noise."""
        async with self._lock:
            t = time.monotonic() - self._start
            # DC voltage: slow oscillation ±20 around 3350
            self._regs[0] = int(3350 + 20 * math.sin(t / 30) + random.gauss(0, 2))
            # AC current: faster oscillation
            self._regs[1] = int(125 + 25 * math.sin(t / 10) + random.gauss(0, 1))
            # Power factor: near unity, small variation
            self._regs[2] = max(900, min(1000, int(985 + random.gauss(0, 3))))
            # Fault register: randomly trigger bit 2 (over-temperature) ~1% of the time
            if random.random() < 0.01:
                self._regs[3] = 0x0004   # over-temperature
            else:
                self._regs[3] = 0
            # Temperature: slow climb during "operation"
            self._regs[5] = int(250 + 20 * math.sin(t / 60) + random.gauss(0, 1))
            # Output power: follows current × voltage roughly
            self._regs[6] = int(self._regs[1] * self._regs[0] // 1000)
            # Runtime hours: increment each update cycle (~every 2s → /1800 per hour)
            self._regs[8] = min(65535, self._regs[8] + 1)

    async def get_all(self) -> list[int]:
        async with self._lock:
            return list(self._regs)

    async def get(self, address: int, count: int = 1) -> list[int]:
        async with self._lock:
            return self._regs[address: address + count]

    async def set(self, address: int, value: int):
        async with self._lock:
            if 0 <= address < len(self._regs):
                self._regs[address] = value


# ── Server ────────────────────────────────────────────────────────────────────

async def run_server(host: str = "127.0.0.1", port: int = 5020,
                     store: Optional[RegisterStore] = None,
                     stop_event: Optional[asyncio.Event] = None) -> None:
    """Run a pymodbus async TCP slave."""
    try:
        from pymodbus.server import StartAsyncTcpServer
        from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
        from pymodbus.datastore import ModbusSequentialDataBlock
    except ImportError:
        print("[server] ERROR: pymodbus not installed. Run: pip install pymodbus>=3.0")
        return

    if store is None:
        store = RegisterStore()

    # Build pymodbus datastore from our register store
    initial = await store.get_all()
    # Pad to 100 registers so out-of-range reads return exception
    initial += [0] * (100 - len(initial))

    slave_ctx = ModbusSlaveContext(
        hr=ModbusSequentialDataBlock(0, initial),
    )
    server_ctx = ModbusServerContext(slaves=slave_ctx, single=True)

    print(f"[server] Modbus TCP slave starting on {host}:{port}")
    print(f"[server] Initial registers: {initial[:10]}")

    # Start background register updater
    async def _updater():
        while stop_event is None or not stop_event.is_set():
            await store.update()
            regs = await store.get_all()
            # Sync pymodbus store
            slave_ctx.setValues(3, 0, regs)
            await asyncio.sleep(2)

    asyncio.create_task(_updater())

    try:
        await StartAsyncTcpServer(context=server_ctx, address=(host, port))
    except Exception as e:
        print(f"[server] Error: {e}")


# ── Anomalous traffic client ──────────────────────────────────────────────────

async def generate_traffic(host: str = "127.0.0.1", port: int = 5020,
                           duration: int = 60, anomaly_rate: float = 0.1,
                           stop_event: Optional[asyncio.Event] = None) -> None:
    """
    Generate mixed normal + anomalous Modbus TCP traffic.

    Normal:  FC 3 (Read Holding Registers) — reads registers 0-9
    Anomaly (10%): FC 6 (Write Single Register) — unexpected write
    Anomaly (5%):  FC 3 with out-of-range address — triggers exception 0x02
    """
    try:
        from pymodbus.client import AsyncModbusTcpClient
    except ImportError:
        print("[client] ERROR: pymodbus not installed. Run: pip install pymodbus>=3.0")
        return

    print(f"[client] Connecting to {host}:{port} — {duration}s of traffic, anomaly_rate={anomaly_rate}")
    await asyncio.sleep(1)  # give server time to start

    async with AsyncModbusTcpClient(host=host, port=port) as client:
        end_time = time.monotonic() + duration
        req_count = 0
        write_count = 0
        exception_count = 0

        while time.monotonic() < end_time:
            if stop_event and stop_event.is_set():
                break

            roll = random.random()

            try:
                if roll < anomaly_rate * 0.5:
                    # Anomaly: write to register 4 (mode change) — unauthorized
                    new_mode = random.randint(0, 3)
                    rr = await client.write_register(4, new_mode, slave=1)
                    write_count += 1
                    if not rr.isError():
                        log.debug("[client] WRITE reg=4 val=%d (anomaly)", new_mode)
                    else:
                        log.debug("[client] WRITE rejected (expected on read-only device)")

                elif roll < anomaly_rate:
                    # Anomaly: read out-of-range address → Illegal Data Address (exception 0x02)
                    bad_addr = random.randint(90, 200)
                    rr = await client.read_holding_registers(bad_addr, count=1, slave=1)
                    exception_count += 1
                    log.debug("[client] READ bad_addr=%d (exception trigger)", bad_addr)

                else:
                    # Normal: read registers 0-9
                    rr = await client.read_holding_registers(0, count=10, slave=1)
                    if not rr.isError():
                        log.debug("[client] READ ok: %s", rr.registers[:5])

                req_count += 1

            except Exception as e:
                log.debug("[client] request error: %s", e)

            await asyncio.sleep(random.uniform(0.2, 0.8))

    print(
        f"[client] Done — {req_count} requests, "
        f"{write_count} writes, {exception_count} exception triggers"
    )


# ── Entry point ───────────────────────────────────────────────────────────────

async def _main(args: argparse.Namespace) -> None:
    stop = asyncio.Event()
    store = RegisterStore()
    tasks = []

    if args.mode in ("server", "both"):
        tasks.append(asyncio.create_task(
            run_server(args.host, args.port, store=store, stop_event=stop)
        ))
        await asyncio.sleep(0.5)  # let server bind

    if args.mode in ("client", "both"):
        tasks.append(asyncio.create_task(
            generate_traffic(
                args.host, args.port,
                duration=args.duration,
                anomaly_rate=args.anomaly_rate,
                stop_event=stop,
            )
        ))

    if not tasks:
        print("No mode selected. Use --mode server|client|both")
        return

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[sim] Interrupted.")
        stop.set()
        for t in tasks:
            t.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Modbus TCP ICS Traffic Simulator")
    parser.add_argument("--host",         default="127.0.0.1", help="Bind/connect host")
    parser.add_argument("--port",   "-p", type=int, default=5020, help="TCP port")
    parser.add_argument("--mode",   "-m", choices=["server", "client", "both"],
                        default="both", help="Run mode")
    parser.add_argument("--duration","-d",type=int, default=60,
                        help="Client traffic duration in seconds")
    parser.add_argument("--anomaly-rate", type=float, default=0.1,
                        help="Fraction of requests that are anomalous (0.0–1.0)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    asyncio.run(_main(args))
