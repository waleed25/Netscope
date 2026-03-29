---
name: dnp3-analysis
version: "1.0"
description: >
  Analyze DNP3 SCADA traffic from PCAP captures. Extracts Application Layer
  function codes and object groups, identifies unauthorized Write/Operate
  commands, detects unsolicited responses, and provides an LLM security
  assessment of the SCADA communication patterns.
triggers:
  - "dnp3"
  - "scada"
  - "substation"
  - "rtu"
  - "outstation"
  - "iec 60870"
  - "dnp3 write"
  - "dnp3 anomaly"
  - "binary output command"
  - "direct operate"
tools:
  - dnp3_analyze
  - tshark_filter
  - tshark_expert
parameters:
  pcap_path:
    type: string
    required: false
    description: Path to PCAP/PCAPNG/CAP file. Defaults to current capture.
  max_packets:
    type: integer
    default: 2000
    description: Maximum number of DNP3 packets to analyze.
output_format: TOON + Markdown security assessment
---

## DNP3 Analysis Skill

DNP3 (Distributed Network Protocol 3) is the dominant SCADA protocol for
electric utility substations and water treatment facilities. It is used
for communication between SCADA master stations and Remote Terminal Units (RTUs).

### Protocol Overview

**Message flow:**
```
Master → RTU: Read / Write / Operate
RTU → Master: Response
RTU → Master: Unsolicited Response (spontaneous data)
```

**Port:** UDP/TCP 20000 (standard)

### Function Code Reference

| FC Hex | Name | Security Relevance |
|--------|------|--------------------|
| `0x01` | Read | Normal poll — master requesting data |
| `0x02` | Write | **HIGH** — only master should send |
| `0x03` | Select | Pre-operate handshake |
| `0x04` | Operate | **HIGH** — executes physical action |
| `0x05` | Direct Operate | **CRITICAL** — no handshake, immediate action |
| `0x06` | Direct Operate No Ack | **CRITICAL** — no confirmation |
| `0x0d` | Cold Restart | **HIGH** — reboots outstation |
| `0x0e` | Warm Restart | **HIGH** — restarts outstation |
| `0x14` | Enable Unsolicited | Changes reporting behavior |
| `0x82` | Unsolicited Response | Verify expected from RTU |

### Sensitive Object Groups

| Group | Description | Why Sensitive |
|-------|-------------|---------------|
| 12    | Binary Output Command (CROB) | Controls physical relays |
| 30    | Analog Input | Sensor readings |
| 40    | Analog Output | Setpoint commands |
| 41    | Analog Output Command | Direct output control |
| 50    | Time and Date | Clock synchronization |
| 80    | Internal Indications | Device status flags |

### Tool Usage

```
TOOL: dnp3_analyze
TOOL: dnp3_analyze /path/to/capture.pcap
TOOL: dnp3_analyze /path/to/capture.pcap 5000
```

### What the Analysis Reports

1. **Statistics** (TOON format):
   - Total DNP3 packets, unique sources/destinations
   - Write/Operate command count
   - Unsolicited response count
   - Sensitive object group activity

2. **Function Code Distribution** — identifies which operations dominate

3. **Security Findings** — LLM analysis:
   - Unexpected Write/Operate from non-master hosts
   - Direct Operate without prior Select (SBO bypass)
   - Restart commands during normal operation
   - Unusual unsolicited response patterns

### Display Filters for Drill-Down

```
# After dnp3_analyze, use tshark_filter to get filters:
TOOL: tshark_filter "dnp3 write"
TOOL: tshark_filter "dnp3 direct operate"
TOOL: tshark_filter "dnp3 unsolicited"
```

### Capture DNP3 Traffic

```bash
# BPF filter for DNP3 on standard port
tshark -i eth0 -f "port 20000" -b filesize:102400 -b files:10 -w dnp3.pcap
```

### Integration with Other Tools

- `tshark_expert` — check for Link Layer framing errors in DNP3 frames
- `expert_analyze ics_audit` — comprehensive ICS security assessment
- `modbus_analyze` — if both Modbus and DNP3 are present
