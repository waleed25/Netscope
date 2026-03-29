"""
Multi-Channel Modbus TCP Machine-in-the-Middle Proxy.

Sits transparently between a Modbus master and slave.  All traffic is
forwarded; depending on --tamper mode, responses can be modified to test
Netscope Desktop's anomaly detection.

Tamper modes:
  passthrough       — forward all bytes unchanged (baseline logging)
  log_only          — log each Modbus PDU without modification (default)
  flip_register     — flip bit 0 of the first holding register value in responses
  inject_exception  — replace Read Holding Register responses with exception 0x04
                      (Server Device Failure) to simulate a failing slave

Usage:
  # Start real Modbus slave
  python simulate_modbus.py --mode server --port 5020

  # Start MitM proxy (listens on 5021, forwards to 5020)
  python mc_mitm.py --listen-port 5021 --target-port 5020 --tamper log_only

  # Connect client through proxy
  python simulate_modbus.py --mode client --port 5021

  # Capture the MitM traffic on loopback and analyse
  tshark -i lo0 -f "port 5020 or port 5021" -w mitm.pcap

Dependencies:
  pip install pymodbus>=3.0  (for PDU parsing; proxy works without it)
"""

from __future__ import annotations
import argparse
import asyncio
import logging
import struct
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("mc_mitm")


# ── Modbus PDU helpers ────────────────────────────────────────────────────────

MBAP_HEADER_LEN = 7   # transaction_id(2) + protocol_id(2) + length(2) + unit_id(1)


def _parse_mbap(data: bytes) -> Optional[tuple[int, int, int, int]]:
    """Parse Modbus MBAP header. Returns (transaction_id, protocol_id, length, unit_id) or None."""
    if len(data) < MBAP_HEADER_LEN:
        return None
    return struct.unpack(">HHHB", data[:MBAP_HEADER_LEN])


def _get_fc(data: bytes) -> Optional[int]:
    """Extract Modbus function code from raw TCP payload."""
    if len(data) < MBAP_HEADER_LEN + 1:
        return None
    return data[MBAP_HEADER_LEN]


def _is_response(data: bytes) -> bool:
    """True if this looks like a Modbus response (server → client)."""
    fc = _get_fc(data)
    # Exception responses have high bit set on FC
    if fc is None:
        return False
    # We treat all FC ≤ 0x7F (non-exception) server-side as responses
    return fc is not None


def _tamper_flip_register(data: bytes) -> bytes:
    """
    Flip bit 0 of the first word in a Read Holding Registers response (FC 3).
    Byte layout: MBAP(7) + FC(1) + byte_count(1) + data_words...
    """
    fc = _get_fc(data)
    if fc != 3:
        return data   # only affect FC 3 responses
    min_len = MBAP_HEADER_LEN + 1 + 1 + 2   # MBAP + FC + byte_count + first word
    if len(data) < min_len:
        return data
    offset = MBAP_HEADER_LEN + 2   # byte after FC and byte_count
    original_word = struct.unpack(">H", data[offset:offset + 2])[0]
    flipped_word  = original_word ^ 0x0001
    return data[:offset] + struct.pack(">H", flipped_word) + data[offset + 2:]


def _tamper_inject_exception(data: bytes) -> bytes:
    """
    Replace a Read Holding Registers response (FC 3) with an exception
    response: FC=0x83, exception_code=0x04 (Server Device Failure).
    """
    fc = _get_fc(data)
    if fc != 3:
        return data

    mbap = _parse_mbap(data)
    if not mbap:
        return data

    transaction_id, protocol_id, _length, unit_id = mbap
    new_length = 3   # unit_id(1) + FC(1) + exception_code(1)
    new_mbap = struct.pack(">HHHB", transaction_id, protocol_id, new_length, unit_id)
    new_pdu  = bytes([0x83, 0x04])   # exception FC=0x83, code=0x04
    return new_mbap + new_pdu


# ── Audit logger ──────────────────────────────────────────────────────────────

class AuditLog:
    def __init__(self, path: str):
        self._path = Path(path)
        self._lock = asyncio.Lock()

    async def write(self, direction: str, data: bytes, tampered: bool = False):
        fc = _get_fc(data)
        mbap = _parse_mbap(data)
        unit_id = mbap[3] if mbap else "?"
        entry = (
            f"{time.strftime('%H:%M:%S')} {direction:6s} "
            f"fc={fc:#04x if fc else '?'} unit={unit_id} "
            f"len={len(data)} {'[TAMPERED]' if tampered else ''}\n"
        )
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(entry)
        log.debug(entry.rstrip())


# ── MitM proxy ────────────────────────────────────────────────────────────────

class ModbusMitM:
    def __init__(
        self,
        listen_host: str = "127.0.0.1",
        listen_port: int = 5021,
        target_host: str = "127.0.0.1",
        target_port: int = 5020,
        tamper_mode: str = "log_only",
        log_path: str    = "mitm.log",
    ):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.target_host = target_host
        self.target_port = target_port
        self.tamper_mode = tamper_mode
        self.audit       = AuditLog(log_path)
        self._conn_count = 0
        self._server: Optional[asyncio.Server] = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.listen_host,
            port=self.listen_port,
        )
        print(
            f"[mitm] Listening on {self.listen_host}:{self.listen_port} → "
            f"{self.target_host}:{self.target_port}  mode={self.tamper_mode}"
        )
        async with self._server:
            await self._server.serve_forever()

    async def _handle_client(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        self._conn_count += 1
        conn_id = self._conn_count
        peer = client_writer.get_extra_info("peername")
        log.info("[mitm] New connection #%d from %s", conn_id, peer)

        try:
            target_reader, target_writer = await asyncio.open_connection(
                self.target_host, self.target_port
            )
        except ConnectionRefusedError:
            log.warning("[mitm] Cannot connect to target %s:%d — refusing client",
                        self.target_host, self.target_port)
            client_writer.close()
            return

        # Bidirectional forwarding
        tasks = [
            asyncio.create_task(self._forward(client_reader, target_writer, "C→S", tamper=False)),
            asyncio.create_task(self._forward(target_reader, client_writer, "S→C", tamper=True)),
        ]
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            log.debug("[mitm] conn #%d ended: %s", conn_id, e)
        finally:
            for t in tasks:
                t.cancel()
            try:
                target_writer.close()
                await target_writer.wait_closed()
            except Exception:
                pass
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass
            log.info("[mitm] Connection #%d closed", conn_id)

    async def _forward(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        direction: str,
        tamper: bool,
    ) -> None:
        while True:
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=60)
            except asyncio.TimeoutError:
                continue
            if not data:
                break

            modified = data
            was_tampered = False

            if tamper and self.tamper_mode != "passthrough":
                modified, was_tampered = await self._tamper(data)

            await self.audit.write(direction, data, tampered=was_tampered)

            try:
                writer.write(modified)
                await writer.drain()
            except (ConnectionResetError, BrokenPipeError):
                break

    async def _tamper(self, data: bytes) -> tuple[bytes, bool]:
        """Apply tamper mode to data. Returns (modified_data, was_tampered)."""
        if self.tamper_mode == "log_only":
            return data, False

        if self.tamper_mode == "flip_register":
            modified = _tamper_flip_register(data)
            return modified, modified != data

        if self.tamper_mode == "inject_exception":
            modified = _tamper_inject_exception(data)
            return modified, modified != data

        return data, False


# ── Entry point ───────────────────────────────────────────────────────────────

async def _main(args: argparse.Namespace) -> None:
    proxy = ModbusMitM(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        target_host=args.target_host,
        target_port=args.target_port,
        tamper_mode=args.tamper,
        log_path=args.log_file,
    )
    try:
        await proxy.start()
    except KeyboardInterrupt:
        print("\n[mitm] Stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Multi-Channel Modbus TCP MitM Proxy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Tamper modes:
  passthrough       Forward all bytes unchanged
  log_only          Log PDUs without modification (default)
  flip_register     Flip bit 0 of first holding register in FC 3 responses
  inject_exception  Replace FC 3 responses with exception code 0x04 (Device Failure)

Example workflow:
  1. python simulate_modbus.py --mode server --port 5020
  2. python mc_mitm.py --listen-port 5021 --target-port 5020 --tamper inject_exception
  3. python simulate_modbus.py --mode client --port 5021
  4. tshark -i lo -f "port 5020 or port 5021" -w mitm.pcap
  5. Open mitm.pcap in Netscope Desktop → ask agent to analyse
""",
    )
    parser.add_argument("--listen-host",  default="127.0.0.1")
    parser.add_argument("--listen-port",  type=int, default=5021)
    parser.add_argument("--target-host",  default="127.0.0.1")
    parser.add_argument("--target-port",  type=int, default=5020)
    parser.add_argument("--tamper", choices=["passthrough", "log_only",
                                             "flip_register", "inject_exception"],
                        default="log_only")
    parser.add_argument("--log-file", default="mitm.log")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    asyncio.run(_main(args))
