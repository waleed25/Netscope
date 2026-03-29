"""
Modbus tools: modbus_sim, modbus_read, modbus_write, modbus_scan, modbus_analyze, list_modbus_sessions.
"""
from __future__ import annotations
import os
import pathlib

from agent.tools.registry import register, ToolDef, MAX_OUTPUT
from utils import proc


async def run_modbus_sim(args: str) -> str:
    import json
    from modbus.register_maps import lookup
    from modbus.simulator import simulator_manager

    parts = args.strip().split()
    device_type = parts[0] if parts else "plc"
    try:
        port = int(parts[1]) if len(parts) > 1 else 5020
    except ValueError:
        port = 5020

    _key, registers = lookup(device_type, "")
    if not registers:
        return f"[modbus_sim] No register map found for device_type='{device_type}'. Try: sma, fronius, meter, battery, drive, plc."

    session = await simulator_manager.create_session(
        registers,
        label=f"sim-{device_type}-{port}",
        host="127.0.0.1",
        port=port,
        unit_id=1,
        device_type=device_type,
    )
    if session.status == "error":
        return f"[modbus_sim] Failed to start simulator: {session.error}"

    return json.dumps({
        "session_id":    session.session_id,
        "device_type":   device_type,
        "port":          port,
        "unit_id":       1,
        "register_count": len(registers),
        "status":        session.status,
        "note": f"Simulator running on 0.0.0.0:{port} — connect a Modbus client to localhost:{port}",
    })


async def run_modbus_read(args: str) -> str:
    import json
    from modbus.simulator import simulator_manager
    from modbus.client import client_manager

    session_id = args.strip()
    if not session_id:
        return "[modbus_read] Usage: modbus_read <session_id>"

    sim_session = simulator_manager.get_session(session_id)
    if sim_session:
        regs = sim_session.read_registers()
        return json.dumps({
            "session_id": session_id,
            "source":     "simulator",
            "device_type": sim_session.device_type,
            "registers":  regs[:20],
            "total_regs": len(regs),
        })

    client_session = client_manager.get_session(session_id)
    if client_session:
        regs = client_session.get_latest()
        return json.dumps({
            "session_id": session_id,
            "source":     "client",
            "device_type": client_session.device_type,
            "host":       client_session.host,
            "port":       client_session.port,
            "registers":  regs[:20],
            "total_regs": len(regs),
            "status":     client_session.status,
        })

    return f"[modbus_read] Session '{session_id}' not found. Use modbus_sim or modbus_client to create one."


async def run_modbus_write(args: str) -> str:
    import json
    from modbus.simulator import simulator_manager
    from modbus.client import client_manager

    parts = args.strip().split()
    if len(parts) < 3:
        return "[modbus_write] Usage: modbus_write <session_id> <address> <value>"

    session_id = parts[0]
    try:
        address = int(parts[1])
        value   = int(parts[2])
    except ValueError:
        return "[modbus_write] address and value must be integers."

    if not (0 <= address <= 65535):
        return f"[modbus_write] address must be 0–65535, got {address}."
    if not (0 <= value <= 65535):
        return f"[modbus_write] value must be 0–65535, got {value}."

    sim_session = simulator_manager.get_session(session_id)
    if sim_session:
        ok = sim_session.write_register(address, value)
        return json.dumps({"ok": ok, "session_id": session_id, "address": address, "value": value, "source": "simulator"})

    result = await client_manager.write_register(session_id, address, value)
    if result.get("error") == "Session not found":
        return f"[modbus_write] Session '{session_id}' not found."
    return json.dumps({**result, "session_id": session_id, "source": "client"})


async def run_modbus_scan(args: str) -> str:
    import json
    from modbus.scanner import scan_network, scan_hosts

    targets = args.strip()
    if not targets:
        return "[modbus_scan] Usage: modbus_scan <cidr>  or  modbus_scan <ip1,ip2,...>"

    try:
        if "/" in targets:
            results = await scan_network(targets, timeout=1.5, max_concurrent=30)
        else:
            hosts = [h.strip() for h in targets.split(",") if h.strip()]
            results = await scan_hosts(hosts, timeout=2.0)
    except ValueError as e:
        return f"[modbus_scan] {e}"
    except Exception as e:
        return f"[modbus_scan] Scan error: {e}"

    if not results:
        return json.dumps({"targets": targets, "found": 0, "message": "No Modbus devices found."})

    return json.dumps({"targets": targets, "found": len(results), "devices": results})


async def run_modbus_analyze(args: str) -> str:
    from modbus.wireshark_analyzer import analyze_capture

    parts = args.strip().split()
    if not parts:
        return "[modbus_analyze] Usage: modbus_analyze <pcap_path> [max_packets]"

    pcap_path_raw = parts[0]
    max_packets = int(parts[1]) if len(parts) > 1 else 5000

    try:
        pcap_path = str(pathlib.Path(pcap_path_raw).resolve())
    except Exception:
        return f"[modbus_analyze] Invalid path: {pcap_path_raw}"

    path_lower = pcap_path.lower()
    _BLOCKED_PREFIXES = (
        r"c:\windows", r"c:\program files", r"c:\programdata",
        r"c:\users\default", r"c:\system",
    )
    if any(path_lower.startswith(p) for p in _BLOCKED_PREFIXES):
        return f"[modbus_analyze] Path not allowed: {pcap_path}"
    if not any(path_lower.endswith(ext) for ext in (".pcap", ".pcapng", ".cap")):
        return f"[modbus_analyze] Only .pcap/.pcapng/.cap files are allowed."
    if not os.path.exists(pcap_path):
        return f"[modbus_analyze] File not found: {pcap_path}"
    if not os.path.isfile(pcap_path):
        return f"[modbus_analyze] Path is not a file: {pcap_path}"

    try:
        result = await analyze_capture(pcap_path, filter_str="modbus || modbus.tcp", max_packets=max_packets)
        return result
    except Exception as e:
        return f"[modbus_analyze] Error: {str(e)}"


async def run_list_modbus_sessions(args: str = "") -> str:
    import json
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
    return json.dumps({"sessions": sessions, "count": len(sessions)})


# ── Registration ─────────────────────────────────────────────────────────────

_MODBUS_KW = {
    "modbus", "register", "simulator", "plc", "scada", "ics",
    "ot", "inverter", "sma", "fronius", "meter", "battery",
    "drive", "unit_id", "coil", "holding",
}

register(ToolDef(
    name="modbus_sim", category="modbus",
    description="start simulator (sma|fronius|meter|battery|drive|plc)",
    args_spec="<type> [port]", runner=run_modbus_sim,
    safety="write", keywords=_MODBUS_KW,
))

register(ToolDef(
    name="modbus_read", category="modbus",
    description="read registers from session",
    args_spec="<session_id>", runner=run_modbus_read,
    safety="read", keywords=_MODBUS_KW,
))

register(ToolDef(
    name="modbus_write", category="modbus",
    description="write register (0-65535)",
    args_spec="<id> <addr> <val>", runner=run_modbus_write,
    safety="write", keywords=_MODBUS_KW,
))

register(ToolDef(
    name="modbus_scan", category="modbus",
    description="scan for Modbus TCP devices",
    args_spec="<targets>", runner=run_modbus_scan,
    safety="dangerous", keywords=_MODBUS_KW,
))

register(ToolDef(
    name="modbus_analyze", category="modbus",
    description="analyze PCAP for Modbus issues",
    args_spec="<pcap> [n]", runner=run_modbus_analyze,
    safety="read", keywords=_MODBUS_KW,
))

register(ToolDef(
    name="list_modbus_sessions", category="modbus",
    description="list active simulator/client sessions",
    args_spec="", runner=run_list_modbus_sessions,
    safety="read", keywords=_MODBUS_KW,
))


# ── Modbus Forensics (raw TOON, no nested LLM call) ─────────────────────────

async def run_modbus_forensics(args: str) -> str:
    """Focused tshark field extraction for Modbus forensic analysis.

    Returns TOON-formatted table directly — no internal LLM call.
    The agent's outer loop reasons over the structured data.
    """
    import asyncio
    from utils.tshark_utils import find_tshark
    from utils.toon import modbus_fields_to_toon
    from utils.sanitize import sanitize_tshark_output, validate_read_only_command

    parts_args = args.strip().split()

    # Resolve pcap path: arg or current capture
    if parts_args:
        pcap_raw = parts_args[0]
    else:
        try:
            from api.routes import _current_capture_file
            pcap_raw = _current_capture_file
        except Exception:
            pcap_raw = ""
    if not pcap_raw:
        return "[modbus_forensics] No PCAP path. Provide one or load a capture first."

    max_packets = int(parts_args[1]) if len(parts_args) > 1 else 2000

    try:
        pcap_path = str(pathlib.Path(pcap_raw).resolve())
    except Exception:
        return f"[modbus_forensics] Invalid path: {pcap_raw}"

    path_lower = pcap_path.lower()
    _BLOCKED_PREFIXES = (
        r"c:\windows", r"c:\program files", r"c:\programdata",
        r"c:\users\default", r"c:\system",
    )
    if any(path_lower.startswith(p) for p in _BLOCKED_PREFIXES):
        return f"[modbus_forensics] Path not allowed: {pcap_path}"
    if not any(path_lower.endswith(ext) for ext in (".pcap", ".pcapng", ".cap")):
        return "[modbus_forensics] Only .pcap/.pcapng/.cap files are allowed."
    if not os.path.isfile(pcap_path):
        return f"[modbus_forensics] File not found: {pcap_path}"

    tshark = find_tshark()
    if not tshark:
        return "[tshark not found] Install Wireshark."

    cmd = [
        tshark, "-r", pcap_path, "-n",
        "-Y", "modbus",
        "-c", str(max_packets),
        "-T", "fields", "-E", "separator=\t",
        "-e", "frame.number",
        "-e", "frame.time_relative",
        "-e", "modbus.func_code",
        "-e", "modbus.unit_id",
        "-e", "ip.src",
        "-e", "ip.dst",
        "-e", "modbus.exception_code",
    ]

    if not validate_read_only_command(cmd):
        return "[safety] Command rejected."

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: proc.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=90,
            ),
        )
    except Exception as e:
        return f"[modbus_forensics error] {e}"

    if result.returncode != 0 and not result.stdout.strip():
        return f"[tshark error] {result.stderr[:300]}"

    raw = sanitize_tshark_output(result.stdout)
    if not raw.strip():
        return "[modbus_forensics] No Modbus packets found in capture."

    return modbus_fields_to_toon(raw, "MODBUS_FORENSICS")


register(ToolDef(
    name="modbus_forensics", category="modbus",
    description="extract Modbus fields from PCAP as TOON table (raw data, no LLM)",
    args_spec="[pcap_path] [max_packets]",
    runner=run_modbus_forensics,
    safety="read",
    keywords={"modbus", "forensics", "fc", "function_code", "exception"},
))


# ── New tools: diagnostics, write_multi, sunspec_discover, set_waveform, inject_exception ──

def _parse_kv(parts: list[str]) -> dict[str, str]:
    """Parse key=value tokens from a parts list. Returns dict of matched pairs."""
    kv: dict[str, str] = {}
    for p in parts:
        if "=" in p:
            k, _, v = p.partition("=")
            kv[k.strip()] = v.strip()
    return kv


async def run_modbus_diagnostics(args: str) -> str:
    session_id = args.strip().split()[0] if args.strip() else ""
    if not session_id:
        return "[modbus_diagnostics] Usage: modbus_diagnostics <session_id>"

    try:
        from modbus.diagnostics import diagnostics_engine
    except ImportError as e:
        return f"Error: {e}"

    stats = diagnostics_engine.get_stats(session_id)

    rtt = stats.get("rtt", {})
    exc_list = stats.get("exceptions", [])
    total_exc = sum(e.get("count", 0) for e in exc_list)
    exc_summary = ", ".join(
        f"EC{e['ec']:02d}×{e['count']}" for e in exc_list[:5]
    )
    exc_str = f"{total_exc} total ({exc_summary})" if exc_list else "0"

    req_rate = stats.get("req_rate", 0.0)
    total_polls = stats.get("total_polls", 0)

    recent_txns = stats.get("transactions", [])[:5]
    txn_lines = []
    for t in recent_txns:
        status_tag = f"EC{t['ec']:02d}" if t.get("ec") else t.get("status", "ok")
        txn_lines.append(
            f"  #{t['seq']} FC{t['fc']} @{t['addr']} {t['rtt_ms']}ms [{status_tag}]"
        )

    lines = [
        f"Session: {session_id}",
        f"RTT: avg={rtt.get('avg', 0)}ms p50={rtt.get('p50', 0)}ms "
        f"p95={rtt.get('p95', 0)}ms p99={rtt.get('p99', 0)}ms",
        f"Exceptions: {exc_str}",
        f"Req rate: {req_rate}/s, Total polls: {total_polls}",
    ]
    if txn_lines:
        lines.append("Recent transactions:")
        lines.extend(txn_lines)
    return "\n".join(lines)


async def run_modbus_write_multi(args: str) -> str:
    parts = args.strip().split()
    if len(parts) < 4:
        return (
            "[modbus_write_multi] Usage: modbus_write_multi <session_id> <fc> <addr> <val1> [val2 ...]\n"
            "  fc=6: single register, fc=16: multiple registers, fc=5: single coil, fc=15: multiple coils"
        )

    session_id = parts[0]
    try:
        fc = int(parts[1])
        addr = int(parts[2])
        values = [int(v) for v in parts[3:]]
    except ValueError:
        return "[modbus_write_multi] fc, addr, and values must be integers."

    if fc not in (5, 6, 15, 16):
        return f"[modbus_write_multi] Unsupported fc={fc}. Supported: 5, 6, 15, 16."

    # Validate address and values
    if not (0 <= addr <= 65535):
        return f"[modbus_write_multi] addr must be 0–65535, got {addr}."
    for v in values:
        if fc in (5, 15):
            if v not in (0, 1):
                return f"[modbus_write_multi] coil values must be 0 or 1, got {v}."
        else:
            if not (0 <= v <= 65535):
                return f"[modbus_write_multi] register values must be 0–65535, got {v}."

    try:
        from modbus.simulator import simulator_manager
        from modbus.client import client_manager
    except ImportError as e:
        return f"Error: {e}"

    # Try simulator first
    sim_session = simulator_manager.get_session(session_id)
    if sim_session:
        if fc in (5, 15):
            # Coil write: use first value as bool for fc=5, list for fc=15
            if fc == 5:
                ok = sim_session.write_register(addr, int(bool(values[0])))
            else:
                # fc=15: write each coil address individually (simulator stores as registers)
                for i, v in enumerate(values):
                    sim_session.write_register(addr + i, int(bool(v)))
                ok = True
        else:
            # fc=6: single register, fc=16: multiple registers
            for i, v in enumerate(values):
                ok = sim_session.write_register(addr + i, v)
        return f"ok — wrote {len(values)} value(s) to {session_id} @{addr} via FC{fc} (simulator)"

    # Try client
    client_session = client_manager.get_session(session_id)
    if client_session:
        try:
            if fc == 5:
                result = await client_session.write_coil(addr, bool(values[0]))
            elif fc == 6:
                result = await client_session.write_register(addr, values[0])
            elif fc == 15:
                result = await client_session.write_coils(addr, [bool(v) for v in values])
            elif fc == 16:
                result = await client_session.write_registers(addr, values)
            else:
                return f"[modbus_write_multi] Unsupported fc={fc}."
        except Exception as e:
            return f"Error: {e}"
        if not result.get("ok"):
            return f"Error: {result.get('error', 'Write failed')}"
        return f"ok — wrote {len(values)} value(s) to {session_id} @{addr} via FC{fc} (client)"

    return f"[modbus_write_multi] Session '{session_id}' not found."


async def run_modbus_sunspec_discover(args: str) -> str:
    parts = args.strip().split()
    if not parts:
        return "[modbus_sunspec_discover] Usage: modbus_sunspec_discover <host> [port] [unit_id]"

    host = parts[0]
    try:
        port = int(parts[1]) if len(parts) > 1 else 502
        unit_id = int(parts[2]) if len(parts) > 2 else 1
    except ValueError:
        return "[modbus_sunspec_discover] port and unit_id must be integers."

    try:
        from modbus.sunspec import SunSpecClient
    except ImportError as e:
        return f"Error: {e}"

    try:
        result = await SunSpecClient.discover(host, port, unit_id)
    except Exception as e:
        return f"Error: {e}"

    if not result.get("found"):
        return f"No SunSpec marker found on {host}:{port} unit_id={unit_id}"

    base_addr = result.get("base_address", "?")
    models = result.get("models", [])
    lines = [f"Found SunSpec at {base_addr} on {host}:{port} unit_id={unit_id}:"]
    for m in models:
        did = m.get("did", "?")
        name = m.get("name", "Unknown")
        length = m.get("length", "?")
        lines.append(f"  - DID {did} ({name}): {length} regs")
    if not models:
        lines.append("  (no model blocks found)")
    return "\n".join(lines)


async def run_modbus_set_waveform(args: str) -> str:
    parts = args.strip().split()
    if len(parts) < 3:
        return (
            "[modbus_set_waveform] Usage: modbus_set_waveform <session_id> <addr> <sine|ramp|script> [params...]\n"
            "  sine: amplitude=<n> period_s=<n> dc_offset=<n>\n"
            "  ramp: start=<n> step=<n> min_val=<n> max_val=<n>\n"
            "  script: expression=<expr>"
        )

    session_id = parts[0]
    try:
        addr = int(parts[1])
    except ValueError:
        return "[modbus_set_waveform] addr must be an integer."

    waveform_type = parts[2].lower()
    kv = _parse_kv(parts[3:])

    if waveform_type not in ("sine", "ramp", "script"):
        return f"[modbus_set_waveform] Unknown waveform type '{waveform_type}'. Use sine, ramp, or script."

    try:
        from modbus.waveforms import SineWave, Ramp, ScriptWave
        from modbus.simulator import simulator_manager
    except ImportError as e:
        return f"Error: {e}"

    try:
        if waveform_type == "sine":
            waveform = SineWave(
                amplitude=float(kv.get("amplitude", 1000.0)),
                period_s=float(kv.get("period_s", 10.0)),
                phase_rad=float(kv.get("phase_rad", 0.0)),
                dc_offset=float(kv.get("dc_offset", 1000.0)),
            )
        elif waveform_type == "ramp":
            waveform = Ramp(
                start=int(kv.get("start", 0)),
                step=int(kv.get("step", 10)),
                min_val=int(kv.get("min_val", 0)),
                max_val=int(kv.get("max_val", 65535)),
            )
        else:  # script
            expr = kv.get("expression", "")
            if not expr:
                # Remaining parts after key=value extraction might be plain expression
                non_kv = [p for p in parts[3:] if "=" not in p]
                expr = " ".join(non_kv)
            waveform = ScriptWave(expression=expr)
    except (ValueError, TypeError) as e:
        return f"Error building waveform: {e}"

    ok = simulator_manager.set_waveform(session_id, addr, waveform)
    if not ok:
        return f"[modbus_set_waveform] Session '{session_id}' not found."
    return f"ok — waveform '{waveform_type}' configured on {session_id} @{addr}"


async def run_modbus_inject_exception(args: str) -> str:
    parts = args.strip().split()
    if len(parts) < 4:
        return (
            "[modbus_inject_exception] Usage: modbus_inject_exception <session_id> <addr> <exception_code> <rate>\n"
            "  exception_code: 1=illegal function, 2=illegal address, 3=illegal value, 4=device failure\n"
            "  rate: 0.0–1.0 (0.0 disables injection)"
        )

    session_id = parts[0]
    try:
        addr = int(parts[1])
        exception_code = int(parts[2])
        rate = float(parts[3])
    except ValueError:
        return "[modbus_inject_exception] addr and exception_code must be integers, rate must be a float."

    if not (0 <= addr <= 65535):
        return f"[modbus_inject_exception] addr must be 0–65535, got {addr}."
    if not (1 <= exception_code <= 11):
        return f"[modbus_inject_exception] exception_code must be 1–11, got {exception_code}."
    if not (0.0 <= rate <= 1.0):
        return f"[modbus_inject_exception] rate must be 0.0–1.0, got {rate}."

    try:
        from modbus.simulator import simulator_manager
    except ImportError as e:
        return f"Error: {e}"

    ok = simulator_manager.set_exception_rule(session_id, addr, exception_code, rate)
    if not ok:
        return f"[modbus_inject_exception] Session '{session_id}' not found."

    if rate == 0.0:
        return f"ok — exception injection disabled on {session_id} @{addr}"
    return (
        f"ok — injecting EC{exception_code:02d} at {rate*100:.0f}% probability "
        f"on {session_id} @{addr}"
    )


# ── Register new tools ────────────────────────────────────────────────────────

register(ToolDef(
    name="modbus_diagnostics", category="modbus",
    description="Get RTT stats, exception counts, heatmap, and transaction log for a Modbus session",
    args_spec="<session_id>", runner=run_modbus_diagnostics,
    safety="read", keywords=_MODBUS_KW | {"diagnostics", "rtt", "latency", "stats"},
))

register(ToolDef(
    name="modbus_write_multi", category="modbus",
    description="Write registers or coils to a Modbus session (FC 5/6/15/16)",
    args_spec="<session_id> <fc> <addr> <val1> [val2 ...]", runner=run_modbus_write_multi,
    safety="write", keywords=_MODBUS_KW | {"write", "fc16", "fc6", "coil", "registers"},
))

register(ToolDef(
    name="modbus_sunspec_discover", category="modbus",
    description="Discover SunSpec model blocks on a Modbus TCP device",
    args_spec="<host> [port] [unit_id]", runner=run_modbus_sunspec_discover,
    safety="read", keywords=_MODBUS_KW | {"sunspec", "solar", "pv", "inverter", "discover"},
))

register(ToolDef(
    name="modbus_set_waveform", category="modbus",
    description="Configure a waveform generator on a simulator register (sine/ramp/script)",
    args_spec="<session_id> <addr> <sine|ramp|script> [params...]", runner=run_modbus_set_waveform,
    safety="write", keywords=_MODBUS_KW | {"waveform", "sine", "ramp", "simulate", "generator"},
))

register(ToolDef(
    name="modbus_inject_exception", category="modbus",
    description="Inject Modbus exception responses on a simulator address at a given rate",
    args_spec="<session_id> <addr> <exception_code> <rate_0_to_1>", runner=run_modbus_inject_exception,
    safety="write", keywords=_MODBUS_KW | {"inject", "exception", "fault", "test", "chaos"},
))
