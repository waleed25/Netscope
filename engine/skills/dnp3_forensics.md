---
name: dnp3-forensics
description: >
  Analyze DNP3/SCADA traffic for unauthorized control commands, binary output
  operations, and substation anomalies. Use when user mentions DNP3, substation,
  RTU, outstation, CROB, binary output, analog setpoint, direct operate,
  unsolicited response, or relay control.
license: Proprietary
compatibility: Requires tshark (Wireshark)
metadata:
  category: industrial-security
  triggers:
    - dnp3
    - substation
    - rtu
    - outstation
    - crob
    - binary output
    - analog setpoint
    - direct operate
    - relay
    - iec 60870
    - scada write
  tool_sequence:
    - dnp3_forensics
    - dnp3_analyze
    - generate_insight
  examples:
    - "Check the capture for DNP3 control commands"
    - "Did any outstation receive a direct operate command?"
    - "Find all CROB (binary output) operations in the PCAP"
    - "Are there unsolicited DNP3 responses?"
---

## DNP3 Analysis Workflow

When analyzing DNP3 traffic:

1. **Start with raw forensics**: `dnp3_forensics [pcap]` — extracts all Write/Operate commands (FC 2–6) with security annotations, flags sensitive object groups (CROB, Analog I/O, Time sync)
2. **LLM interpretation**: `dnp3_analyze [pcap]` — statistical summary + security assessment of the session
3. **Generate findings**: `generate_insight ics` — creates a structured security insight

### Critical object groups
| Group | Name | Risk Level |
|---|---|---|
| 12 | CROB — Binary Output Command | CRITICAL — controls relays/breakers |
| 40/41 | Analog Setpoint/Command | HIGH — changes process setpoints |
| 30 | Analog Input (sensor data) | MEDIUM — could indicate manipulation |
| 50 | Time Sync | MEDIUM — replay attack enabler |
| 80 | Device Indications | LOW — status flags |

### Red flags
- **FC 4/5 (Direct Operate)** from IP not in authorized master list = HIGH severity
- **FC 2 (Write)** to Group 12 objects = potential relay control attack
- **Unsolicited responses (FC 0x82)** without prior enable = spoofed outstation
- **Time sync (Group 50) from unknown source** = replay attack prerequisite

Always check source IP against the expected SCADA master address range.
