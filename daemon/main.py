"""
NetScope Capture Daemon — headless elevated process.

Subscribes to Redis command streams, executes privileged operations
(packet capture via pyshark, Modbus TCP, ICS/DNP3 analysis, subnet scanning),
and publishes results back through Redis Streams and Pub/Sub.

This process MUST run with Administrator privileges for raw packet capture
(Npcap/WinPcap requires elevated access).

Communication:
  - Subscribes to: capture.command, modbus.command, tool.request
  - Publishes to:  capture.status, capture.packets, modbus.response, tool.response
  - Pub/Sub:       ns:pubsub:packets (live packet fan-out)
  - Health:        ns:health.daemon (heartbeat)
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import time
from pathlib import Path

# ── Path setup: add shared/ and daemon/ to sys.path ──────────────────────────
_DAEMON_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _DAEMON_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))        # for `shared.*`
sys.path.insert(0, str(_DAEMON_DIR))           # for `capture.*`, `modbus.*`, etc.

from shared.bus import RedisBus
from shared import events

logging.basicConfig(
    level=logging.INFO,
    format="[daemon] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("daemon")

bus = RedisBus(process_name="daemon")


# ── Capture command handler ──────────────────────────────────────────────────

async def handle_capture_commands():
    """Listen for capture.command messages and dispatch to local capture module."""
    from capture import live_capture

    logger.info("Listening on %s", events.CAPTURE_COMMAND)

    async for msg_id, data in bus.subscribe(events.CAPTURE_COMMAND, last_id="$"):
        action = data.get("action", "")
        correlation_id = data.get("_correlation_id", "")
        reply_to = data.get("_reply_to", events.CAPTURE_STATUS)

        try:
            if action == events.CaptureAction.START:
                interface = data.get("interface", "")
                bpf_filter = data.get("bpf_filter", "")
                output_path = data.get("output_path", "")
                await live_capture.start_capture(interface, bpf_filter, output_path=output_path)
                # Start the packet publisher as a side task
                asyncio.create_task(_packet_publish_loop())
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "status": "capturing",
                    "is_capturing": True,
                    "interface": interface,
                })

            elif action == events.CaptureAction.STOP:
                await live_capture.stop_capture()
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "status": "stopped",
                    "is_capturing": False,
                })

            elif action == events.CaptureAction.STATUS:
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "is_capturing": live_capture.is_capturing(),
                    "interface": live_capture.get_active_interface() or "",
                })

            elif action == events.CaptureAction.LIST_INTERFACES:
                ifaces = await live_capture.get_interfaces()
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "interfaces": ifaces,
                })

            elif action == events.CaptureAction.READ_PCAP:
                pcap_path = data.get("pcap_path", "")
                if pcap_path:
                    from capture.pcap_reader import read_pcap_list
                    packets = await read_pcap_list(pcap_path)
                    await bus.publish(reply_to, {
                        "_correlation_id": correlation_id,
                        "packets": packets,
                        "count": len(packets),
                    })
                else:
                    await bus.publish(reply_to, {
                        "_correlation_id": correlation_id,
                        "error": "No pcap_path provided",
                    })

            else:
                logger.warning("Unknown capture action: %s", action)

        except Exception as exc:
            logger.error("capture.command error (%s): %s", action, exc)
            await bus.publish(reply_to, {
                "_correlation_id": correlation_id,
                "error": str(exc),
            })


# ── Packet publisher (drain loop) ────────────────────────────────────────────

_publisher_running = False


async def _packet_publish_loop():
    """Drain the capture queue and publish each packet to Redis Pub/Sub."""
    global _publisher_running
    if _publisher_running:
        return  # already running
    _publisher_running = True

    from capture import live_capture

    logger.info("Packet publisher started")
    try:
        queue = await live_capture.get_packet_queue()
        while live_capture.is_capturing() or not queue.empty():
            drained = 0
            while not queue.empty():
                try:
                    pkt = queue.get_nowait()
                    # Publish via Pub/Sub for real-time fan-out
                    await bus.pubsub_publish(events.PUBSUB_PACKETS, pkt)
                    # Also add to the stream for persistence/replay
                    await bus.publish(events.CAPTURE_PACKETS, pkt, maxlen=50000)
                    drained += 1
                    # Yield every 50 packets to avoid starving the event loop
                    if drained % 50 == 0:
                        await asyncio.sleep(0)
                except asyncio.QueueEmpty:
                    break
                except Exception as e:
                    logger.error("Packet publish error: %s", e)
            await asyncio.sleep(0.02)  # 20ms poll — ~50 drain cycles/sec
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("Packet publisher error: %s", e)
    finally:
        _publisher_running = False
        logger.info("Packet publisher stopped")


# ── Modbus command handler ───────────────────────────────────────────────────

async def handle_modbus_commands():
    """Listen for modbus.command messages and dispatch to local modbus modules."""
    logger.info("Listening on %s", events.MODBUS_COMMAND)

    async for msg_id, data in bus.subscribe(events.MODBUS_COMMAND, last_id="$"):
        action = data.get("action", "")
        correlation_id = data.get("_correlation_id", "")
        reply_to = data.get("_reply_to", events.MODBUS_RESPONSE)

        try:
            result = await _dispatch_modbus(action, data)
            await bus.publish(reply_to, {
                "_correlation_id": correlation_id,
                **result,
            })
        except Exception as exc:
            logger.error("modbus.command error (%s): %s", action, exc)
            await bus.publish(reply_to, {
                "_correlation_id": correlation_id,
                "error": str(exc),
            })


async def _dispatch_modbus(action: str, data: dict) -> dict:
    """Route a modbus action to the appropriate local function."""
    if action == events.ModbusAction.SIM_CREATE:
        from modbus.register_maps import lookup
        from modbus.simulator import simulator_manager

        device_type = data.get("device_type", "plc")
        port = data.get("port", 5020)
        _key, registers = lookup(device_type, "")
        if not registers:
            return {"error": f"No register map for '{device_type}'"}

        session = await simulator_manager.create_session(
            registers,
            label=f"sim-{device_type}-{port}",
            host="127.0.0.1",
            port=port,
            unit_id=data.get("unit_id", 1),
            device_type=device_type,
        )
        if session.status == "error":
            return {"error": session.error}
        return {
            "session_id": session.session_id,
            "device_type": device_type,
            "port": port,
            "status": session.status,
        }

    elif action == events.ModbusAction.SIM_READ:
        from modbus.simulator import simulator_manager
        session_id = data.get("session_id", "")
        sess = simulator_manager.get_session(session_id)
        if not sess:
            return {"error": f"Session '{session_id}' not found"}
        regs = sess.read_registers()
        return {
            "session_id": session_id,
            "registers": regs[:20],
            "total_regs": len(regs),
        }

    elif action == events.ModbusAction.SIM_WRITE:
        from modbus.simulator import simulator_manager
        session_id = data.get("session_id", "")
        address = data.get("address", 0)
        value = data.get("value", 0)
        sess = simulator_manager.get_session(session_id)
        if not sess:
            return {"error": f"Session '{session_id}' not found"}
        ok = sess.write_register(address, value)
        return {"ok": ok, "address": address, "value": value}

    elif action == events.ModbusAction.LIST_SESSIONS:
        sessions = []
        try:
            from modbus.simulator import simulator_manager
            for sid, s in getattr(simulator_manager, "_sessions", {}).items():
                sessions.append({
                    "session_id": sid,
                    "type": "simulator",
                    "device_type": getattr(s, "device_type", ""),
                    "status": getattr(s, "status", ""),
                    "port": getattr(s, "port", None),
                })
        except Exception:
            pass
        try:
            from modbus.client import client_manager
            for sid, s in getattr(client_manager, "_sessions", {}).items():
                sessions.append({
                    "session_id": sid,
                    "type": "client",
                    "device_type": getattr(s, "device_type", ""),
                    "status": getattr(s, "status", ""),
                    "host": getattr(s, "host", ""),
                    "port": getattr(s, "port", None),
                })
        except Exception:
            pass
        return {"sessions": sessions, "count": len(sessions)}

    elif action == events.ModbusAction.SCAN:
        from modbus.scanner import scan_network, scan_hosts
        targets = data.get("cidr", "")
        if "/" in targets:
            results = await scan_network(targets, timeout=1.5, max_concurrent=30)
        else:
            hosts = [h.strip() for h in targets.split(",") if h.strip()]
            results = await scan_hosts(hosts, timeout=2.0)
        return {"targets": targets, "found": len(results), "devices": results}

    elif action == events.ModbusAction.DIAGNOSTICS:
        from modbus.diagnostics import diagnostics_engine
        session_id = data.get("session_id", "")
        stats = diagnostics_engine.get_stats(session_id)
        return {"session_id": session_id, **stats}

    else:
        return {"error": f"Unknown modbus action: {action}"}


# ── Tool request handler (Engine → Daemon) ───────────────────────────────────

async def handle_tool_requests():
    """
    Listen for tool.request from the Engine process.
    Used when AI tools need to execute privileged operations.
    """
    logger.info("Listening on %s", events.TOOL_REQUEST)

    async for msg_id, data in bus.subscribe(events.TOOL_REQUEST, last_id="$"):
        tool_name = data.get("tool_name", "")
        args = data.get("args", "")
        correlation_id = data.get("_correlation_id", "")
        reply_to = data.get("_reply_to", events.TOOL_RESPONSE)

        start = time.monotonic()
        try:
            result = await _execute_tool(tool_name, args)
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            await bus.publish(reply_to, {
                "_correlation_id": correlation_id,
                "tool": tool_name,
                "status": "ok",
                "output": result,
                "duration_ms": duration_ms,
            })
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            logger.error("tool.request error (%s): %s", tool_name, exc)
            await bus.publish(reply_to, {
                "_correlation_id": correlation_id,
                "tool": tool_name,
                "status": "error",
                "output": str(exc),
                "duration_ms": duration_ms,
            })


async def _execute_tool(tool_name: str, args: str) -> str:
    """Execute a daemon-side tool by name."""
    # Capture tool
    if tool_name == "capture":
        # simplified — the full version (with drain loop) is handled via capture.command
        return "[capture] Use capture.command stream for full capture management."

    # Subnet scanner
    if tool_name == "subnet_scan":
        from capture.subnet_scanner import scan_subnet
        results = await scan_subnet(args.strip(), max_concurrent=64, timeout=1.0)
        return json.dumps([h.to_dict() for h in results if h.alive])

    # Modbus analyze (pcap)
    if tool_name == "modbus_analyze":
        from modbus.wireshark_analyzer import analyze_capture
        parts = args.strip().split()
        pcap_path = parts[0] if parts else ""
        max_packets = int(parts[1]) if len(parts) > 1 else 5000
        return await analyze_capture(pcap_path, filter_str="modbus || modbus.tcp", max_packets=max_packets)

    # Modbus forensics
    if tool_name == "modbus_forensics":
        import pathlib
        from utils.tshark_utils import find_tshark
        from utils.toon import modbus_fields_to_toon
        from utils.sanitize import sanitize_tshark_output, validate_read_only_command
        from utils import proc

        parts = args.strip().split()
        pcap_raw = parts[0] if parts else ""
        if not pcap_raw:
            return "[modbus_forensics] No PCAP path provided."
        max_packets = int(parts[1]) if len(parts) > 1 else 2000
        pcap_path = str(pathlib.Path(pcap_raw).resolve())

        tshark = find_tshark()
        if not tshark:
            return "[tshark not found] Install Wireshark."

        cmd = [
            tshark, "-r", pcap_path, "-n",
            "-Y", "modbus", "-c", str(max_packets),
            "-T", "fields", "-E", "separator=\t",
            "-e", "frame.number", "-e", "frame.time_relative",
            "-e", "modbus.func_code", "-e", "modbus.unit_id",
            "-e", "ip.src", "-e", "ip.dst",
            "-e", "modbus.exception_code",
        ]
        if not validate_read_only_command(cmd):
            return "[safety] Command rejected."

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: proc.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=90),
        )
        if result.returncode != 0 and not result.stdout.strip():
            return f"[tshark error] {result.stderr[:300]}"
        raw = sanitize_tshark_output(result.stdout)
        if not raw.strip():
            return "[modbus_forensics] No Modbus packets found."
        return modbus_fields_to_toon(raw, "MODBUS_FORENSICS")

    return f"[daemon] Unknown tool: {tool_name}"


# ── Main entry point ─────────────────────────────────────────────────────────

async def main():
    """Start the daemon and run all command handlers concurrently."""
    logger.info("NetScope Capture Daemon starting...")
    await bus.connect(retry=True, max_retries=60, delay=1.0)
    logger.info("Connected to Redis — daemon ready")

    # Graceful shutdown on SIGTERM / Ctrl+C
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for all signals
            pass

    # Graceful shutdown via Pub/Sub (for when Electron app quits)
    async def listen_for_shutdown():
        async for _ in bus.pubsub_subscribe("ns:daemon.shutdown"):
            logger.info("Received shutdown signal from UI — terminating")
            stop_event.set()
            for t in tasks:
                t.cancel()
            break

    # Run all handlers concurrently
    tasks = [
        asyncio.create_task(handle_capture_commands()),
        asyncio.create_task(handle_modbus_commands()),
        asyncio.create_task(handle_tool_requests()),
        asyncio.create_task(bus.heartbeat_loop(events.HEALTH_DAEMON, interval_s=5.0)),
        asyncio.create_task(listen_for_shutdown()),
    ]

    try:
        # Wait until stop_event is set or tasks complete/cancel
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait([stop_task, *tasks], return_when=asyncio.FIRST_COMPLETED)
        if stop_task in done:
            raise asyncio.CancelledError()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Cleanup capture if running
        try:
            from capture import live_capture
            if live_capture.is_capturing():
                await live_capture.stop_capture()
        except Exception:
            pass
        await bus.close()
        logger.info("Daemon shut down cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
