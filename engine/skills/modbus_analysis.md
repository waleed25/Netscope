---
name: modbus-analysis
description: >
  Analyze Modbus TCP sessions, detect unauthorized function codes, coil writes,
  register manipulation, replay attacks, and broadcast storms in ICS/OT networks.
  Use when the user mentions Modbus, PLC, SCADA, function code (FC), holding
  register, coil, unit ID, inverter, SMA, Fronius, or industrial protocol.
license: Proprietary
compatibility: Requires pymodbus; optional tshark for PCAP analysis
metadata:
  category: industrial-security
  triggers:
    - modbus
    - plc
    - scada
    - coil
    - register
    - holding
    - function code
    - fc
    - unit id
    - inverter
    - sma
    - fronius
    - industrial
    - iec 62443
  tool_sequence:
    - list_modbus_sessions
    - modbus_read
    - modbus_forensics
    - modbus_analyze
    - generate_insight
  examples:
    - "Are there any Modbus anomalies in the capture?"
    - "Start a Modbus simulator for a SMA inverter"
    - "Read registers from the active PLC session"
    - "Check for unauthorized FC16 writes"
    - "Scan for Modbus devices on 192.168.1.0/24"
---

## Modbus Analysis Workflow

When the user asks about Modbus traffic or ICS device behavior:

1. **Check for active sessions first**: `list_modbus_sessions` — get session IDs before reading
2. **If a PCAP is loaded**: use `modbus_forensics <pcap>` for raw function-code extraction (TOON format), then `modbus_analyze <pcap>` for LLM interpretation
3. **If live capture**: use `capture 30` then `expert_analyze ics_audit`
4. **For simulators**: `modbus_sim <type> [port]` — valid types: sma, fronius, meter, battery, drive, plc

### Security flags to look for
- **FC 5/6/15/16**: coil/register writes — should only come from authorized masters
- **Broadcast (unit_id=0)**: rare in well-designed networks, often an attack vector
- **Exception codes > 0**: device refusing commands — possible access control violation
- **Repeated FC 1-4 from unknown source**: register enumeration/scanning

### IEC 62443 alignment
- Zone 0 (Safety): any Modbus write to safety PLC = immediate escalation
- Zone 1 (Control): monitor FC 5/6/15/16 strictly
- Zone 2 (Operations): baseline read patterns, alert on deviation

Report severity as: CRITICAL / HIGH / MEDIUM / LOW / INFO
