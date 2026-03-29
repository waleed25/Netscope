---
name: modbus-analysis
version: "1.0"
description: >
  Comprehensive Modbus TCP analysis toolkit: simulate devices, scan networks,
  read/write registers, and analyze PCAP captures for Modbus anomalies and
  security issues.
triggers:
  - "modbus"
  - "plc"
  - "scada"
  - "ics modbus"
  - "holding registers"
  - "modbus exception"
  - "modbus analyze"
  - "inverter"
  - "energy meter"
tools:
  - modbus_sim
  - modbus_read
  - modbus_write
  - modbus_scan
  - modbus_analyze
  - list_modbus_sessions
parameters:
  device_type:
    type: enum
    values: [sma, fronius, meter, battery, drive, plc]
    description: Type of Modbus device to simulate
  pcap_path:
    type: string
    description: Path to PCAP file for modbus_analyze
output_format: JSON + Markdown analysis
---

## Modbus Analysis Skill

### Device Simulation

Spin up a realistic Modbus TCP slave with live register values:

| Device Type | Description | Default Port |
|-------------|-------------|-------------|
| `sma`       | SMA solar inverter | 5020 |
| `fronius`   | Fronius inverter | 5020 |
| `meter`     | Energy meter | 5020 |
| `battery`   | Battery system | 5020 |
| `drive`     | Variable frequency drive | 5020 |
| `plc`       | Generic PLC | 5020 |

```
TOOL: modbus_sim plc 5020
TOOL: modbus_sim sma 5021
```

### Register Operations

```
TOOL: modbus_read <session_id>
TOOL: modbus_write <session_id> <address> <value>
TOOL: list_modbus_sessions
```

### Network Scanning

```
TOOL: modbus_scan 192.168.1.0/24
TOOL: modbus_scan 10.0.0.1,10.0.0.2,10.0.0.10
```

### PCAP Analysis

Extracts Modbus packets using tshark and runs LLM analysis:

```
TOOL: modbus_analyze /path/to/capture.pcap
TOOL: modbus_analyze /path/to/capture.pcap 2000
```

**What is detected:**
- Exception responses (codes 1-4 indicate device errors)
- Unexpected write operations (FC 5, 6, 15, 16)
- High error rates suggesting device failure or MitM
- Unusual unit IDs (unauthorized device access)

### Security Considerations for Modbus

Modbus TCP has **no authentication** — any host on the network can:
- Read all holding registers
- Write arbitrary values to any address
- Send commands to any unit ID

**Red flags to watch for:**
- FC 6 (Write Single Register) from unexpected hosts
- FC 16 (Write Multiple Registers) in bulk
- Exception code 4 (Server Device Failure) — device may be unstable
- Repeated exception code 2 (Illegal Data Address) — scanning/probing

### Integration

After PCAP analysis, combine with:
- `tshark_expert` — check for TCP-level anomalies alongside Modbus issues
- `tshark_filter "modbus exception"` — get filter to isolate exception frames
- `expert_analyze ics_audit` — full ICS security audit
