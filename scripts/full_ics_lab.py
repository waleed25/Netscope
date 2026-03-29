"""
Full ICS Lab Orchestrator — One-command ICS test environment.

Launches all components of a realistic ICS network simulation:
  1. Modbus TCP server (simulated PLC with register updates)
  2. Modbus MitM proxy (optional, for anomaly injection)
  3. Modbus TCP client (polls server through proxy)
  4. DNP3 traffic generator (optional, crafted packets to PCAP)
  5. tshark capture on loopback (saves all traffic to PCAP)

After the configured duration, all processes are shut down gracefully
and the PCAP file is ready for analysis in NetScope Desktop.

Usage:
  # Basic lab: Modbus server + client + tshark capture for 60 seconds
  python full_ics_lab.py --duration 60

  # Full lab with MitM + DNP3 + exception injection
  python full_ics_lab.py --duration 120 --tamper inject_exception --include-dnp3

  # Quick test run (30s, no tshark needed)
  python full_ics_lab.py --duration 30 --no-tshark

  # Custom ports
  python full_ics_lab.py --modbus-port 5020 --mitm-port 5021 --duration 60

Dependencies:
  pip install pymodbus>=3.0 scapy
  tshark (Wireshark CLI) must be in PATH for capture mode
"""

from __future__ import annotations
import argparse
import asyncio
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("ics_lab")

# ── Paths ────────────────────────────────────────────────────────────────────

SCRIPTS_DIR = Path(__file__).parent
SIMULATE_MODBUS = SCRIPTS_DIR / "simulate_modbus.py"
MC_MITM         = SCRIPTS_DIR / "mc_mitm.py"
SIMULATE_DNP3   = SCRIPTS_DIR / "simulate_dnp3.py"


# ── Process helpers ──────────────────────────────────────────────────────────

class ManagedProcess:
    """Wrapper around a subprocess with graceful shutdown."""

    def __init__(self, name: str, cmd: list[str], env: Optional[dict] = None):
        self.name = name
        self.cmd = cmd
        self.env = env
        self.proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        env = {**os.environ, **(self.env or {})}
        log.info(f"[{self.name}] Starting: {' '.join(self.cmd)}")
        self.proc = subprocess.Popen(
            self.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            # Use CREATE_NEW_PROCESS_GROUP on Windows for clean shutdown
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if platform.system() == "Windows" else 0,
        )
        log.info(f"[{self.name}] PID {self.proc.pid}")

    def stop(self, timeout: float = 5.0) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        log.info(f"[{self.name}] Stopping PID {self.proc.pid}…")
        try:
            if platform.system() == "Windows":
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.proc.terminate()
            self.proc.wait(timeout=timeout)
            log.info(f"[{self.name}] Stopped gracefully")
        except subprocess.TimeoutExpired:
            log.warning(f"[{self.name}] Force killing…")
            self.proc.kill()
            self.proc.wait(timeout=2)
        except Exception as e:
            log.warning(f"[{self.name}] Error stopping: {e}")
            try:
                self.proc.kill()
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


# ── Lab orchestrator ─────────────────────────────────────────────────────────

class ICSLab:
    """Orchestrates the full ICS lab environment."""

    def __init__(
        self,
        modbus_port: int = 5020,
        mitm_port: int = 5021,
        duration: float = 60.0,
        tamper_mode: str = "log_only",
        pcap_output: str = "ics_lab.pcap",
        include_dnp3: bool = False,
        no_tshark: bool = False,
        no_mitm: bool = False,
        anomaly_rate: float = 0.15,
        python_cmd: Optional[str] = None,
    ):
        self.modbus_port = modbus_port
        self.mitm_port = mitm_port
        self.duration = duration
        self.tamper_mode = tamper_mode
        self.pcap_output = pcap_output
        self.include_dnp3 = include_dnp3
        self.no_tshark = no_tshark
        self.no_mitm = no_mitm
        self.anomaly_rate = anomaly_rate
        self.python = python_cmd or sys.executable
        self.processes: list[ManagedProcess] = []
        self._stop_requested = False

    def _find_loopback_interface(self) -> str:
        """Detect the loopback interface name for tshark."""
        system = platform.system()
        if system == "Windows":
            # Npcap loopback adapter
            return r"\Device\NPF_Loopback"
        elif system == "Darwin":
            return "lo0"
        else:
            return "lo"

    def _check_prerequisites(self) -> list[str]:
        """Check that required scripts and tools exist."""
        issues = []
        if not SIMULATE_MODBUS.exists():
            issues.append(f"Missing: {SIMULATE_MODBUS}")
        if not self.no_mitm and not MC_MITM.exists():
            issues.append(f"Missing: {MC_MITM}")
        if self.include_dnp3 and not SIMULATE_DNP3.exists():
            issues.append(f"Missing: {SIMULATE_DNP3}")
        if not self.no_tshark and not shutil.which("tshark"):
            issues.append("tshark not found in PATH (install Wireshark or use --no-tshark)")
        return issues

    def run(self) -> None:
        """Run the full ICS lab for the configured duration."""
        issues = self._check_prerequisites()
        if issues:
            for issue in issues:
                log.error(f"  {issue}")
            sys.exit(1)

        # Register signal handlers
        def _handle_stop(signum, frame):
            self._stop_requested = True
            log.info("\nStop requested — shutting down lab…")

        signal.signal(signal.SIGINT, _handle_stop)
        signal.signal(signal.SIGTERM, _handle_stop)

        client_port = self.mitm_port if not self.no_mitm else self.modbus_port
        tshark_ports = f"port {self.modbus_port}"
        if not self.no_mitm:
            tshark_ports += f" or port {self.mitm_port}"

        try:
            self._print_banner()

            # 1. Start tshark capture (first so it catches setup traffic)
            if not self.no_tshark:
                iface = self._find_loopback_interface()
                tshark = ManagedProcess("tshark", [
                    "tshark",
                    "-i", iface,
                    "-f", tshark_ports,
                    "-w", self.pcap_output,
                    "-q",  # quiet mode
                ])
                tshark.start()
                self.processes.append(tshark)
                time.sleep(1)  # let tshark initialize

            # 2. Start Modbus server
            server = ManagedProcess("modbus-server", [
                self.python, str(SIMULATE_MODBUS),
                "--mode", "server",
                "--port", str(self.modbus_port),
            ])
            server.start()
            self.processes.append(server)
            time.sleep(1)  # let server bind

            # 3. Start MitM proxy (optional)
            if not self.no_mitm:
                mitm = ManagedProcess("mitm-proxy", [
                    self.python, str(MC_MITM),
                    "--listen-port", str(self.mitm_port),
                    "--target-port", str(self.modbus_port),
                    "--tamper", self.tamper_mode,
                ])
                mitm.start()
                self.processes.append(mitm)
                time.sleep(0.5)

            # 4. Start Modbus client (connects through proxy or directly)
            client = ManagedProcess("modbus-client", [
                self.python, str(SIMULATE_MODBUS),
                "--mode", "client",
                "--port", str(client_port),
                "--duration", str(int(self.duration)),
                "--anomaly-rate", str(self.anomaly_rate),
            ])
            client.start()
            self.processes.append(client)

            # 5. Start DNP3 traffic generator (optional)
            if self.include_dnp3:
                dnp3_pcap = str(Path(self.pcap_output).with_suffix(".dnp3.pcap"))
                dnp3 = ManagedProcess("dnp3-generator", [
                    self.python, str(SIMULATE_DNP3),
                    "--dry-run",
                    "--pcap-output", dnp3_pcap,
                    "--count", str(max(5, int(self.duration / 2))),
                ])
                dnp3.start()
                self.processes.append(dnp3)

            # 6. Wait for duration or stop signal
            log.info(f"\n{'='*60}")
            log.info(f"  ICS Lab running — {self.duration}s remaining")
            log.info(f"  Press Ctrl+C to stop early")
            log.info(f"{'='*60}\n")

            start_time = time.monotonic()
            while not self._stop_requested:
                elapsed = time.monotonic() - start_time
                if elapsed >= self.duration:
                    log.info(f"Duration ({self.duration}s) reached.")
                    break

                # Check if critical processes died
                if not server.is_running:
                    log.error("[modbus-server] Process died unexpectedly!")
                    break
                if not client.is_running:
                    log.warning("[modbus-client] Process exited (may be normal at duration end)")

                remaining = self.duration - elapsed
                if int(remaining) % 15 == 0 and remaining > 1:
                    log.info(f"  {int(remaining)}s remaining…")
                time.sleep(1)

        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        """Gracefully stop all managed processes in reverse order."""
        log.info("\n--- Shutting down ICS lab ---")
        for proc in reversed(self.processes):
            proc.stop()

        if not self.no_tshark and Path(self.pcap_output).exists():
            size = Path(self.pcap_output).stat().st_size
            log.info(f"\nPCAP saved: {self.pcap_output} ({size:,} bytes)")
            log.info(f"Open in NetScope: Import PCAP → select {self.pcap_output}")
        elif self.no_tshark:
            log.info("\n(No tshark capture — use --no-tshark was set)")

        log.info("ICS lab shutdown complete.")

    def _print_banner(self) -> None:
        """Print lab configuration banner."""
        client_port = self.mitm_port if not self.no_mitm else self.modbus_port
        print(f"""
{'='*60}
  NetScope ICS Lab Orchestrator
{'='*60}

  Modbus Server    : 127.0.0.1:{self.modbus_port}
  {'MitM Proxy       : 127.0.0.1:' + str(self.mitm_port) + ' → :' + str(self.modbus_port) if not self.no_mitm else 'MitM Proxy       : disabled'}
  {'Tamper Mode      : ' + self.tamper_mode if not self.no_mitm else ''}
  Client Target    : 127.0.0.1:{client_port}
  Anomaly Rate     : {self.anomaly_rate * 100:.0f}%
  DNP3 Generator   : {'enabled' if self.include_dnp3 else 'disabled'}
  tshark Capture   : {'enabled → ' + self.pcap_output if not self.no_tshark else 'disabled'}
  Duration         : {self.duration}s

{'='*60}
""")


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="One-command ICS lab: Modbus server + MitM proxy + client + tshark capture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  %(prog)s --duration 60                                     # Basic lab
  %(prog)s --duration 120 --tamper inject_exception          # With MitM injection
  %(prog)s --duration 60 --include-dnp3 --pcap-output lab.pcap  # Full ICS + DNP3
  %(prog)s --duration 30 --no-tshark --no-mitm               # Minimal: server + client only
""",
    )
    parser.add_argument("--modbus-port",  type=int, default=5020,
                        help="Modbus server port (default: 5020)")
    parser.add_argument("--mitm-port",    type=int, default=5021,
                        help="MitM proxy listen port (default: 5021)")
    parser.add_argument("--duration",     type=float, default=60,
                        help="Lab duration in seconds (default: 60)")
    parser.add_argument("--tamper",       default="log_only",
                        choices=["passthrough", "log_only", "flip_register", "inject_exception"],
                        help="MitM tamper mode (default: log_only)")
    parser.add_argument("--pcap-output",  default="ics_lab.pcap", metavar="PATH",
                        help="Output PCAP file path (default: ics_lab.pcap)")
    parser.add_argument("--include-dnp3", action="store_true",
                        help="Also generate DNP3 traffic (saved to separate PCAP)")
    parser.add_argument("--no-tshark",    action="store_true",
                        help="Skip tshark capture (useful if tshark not installed)")
    parser.add_argument("--no-mitm",      action="store_true",
                        help="Skip MitM proxy — client connects directly to server")
    parser.add_argument("--anomaly-rate", type=float, default=0.15,
                        help="Probability of anomalous Modbus traffic per cycle (default: 0.15)")
    parser.add_argument("--python",       default=None,
                        help="Python executable path (default: current interpreter)")
    args = parser.parse_args()

    lab = ICSLab(
        modbus_port=args.modbus_port,
        mitm_port=args.mitm_port,
        duration=args.duration,
        tamper_mode=args.tamper,
        pcap_output=args.pcap_output,
        include_dnp3=args.include_dnp3,
        no_tshark=args.no_tshark,
        no_mitm=args.no_mitm,
        anomaly_rate=args.anomaly_rate,
        python_cmd=args.python,
    )
    lab.run()
