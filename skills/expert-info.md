---
name: expert-info
version: "1.0"
description: >
  Run Wireshark's built-in expert analysis on a PCAP file to surface
  pre-calculated TCP errors, retransmissions, malformed packets, and
  protocol warnings without feeding raw JSON to the LLM.
triggers:
  - "expert analysis"
  - "tshark expert"
  - "what errors are in this capture"
  - "retransmissions"
  - "malformed packets"
  - "anomalies in pcap"
  - "wireshark warnings"
tools:
  - tshark_expert
parameters:
  pcap_path:
    type: string
    required: false
    description: >
      Absolute path to a .pcap, .pcapng, or .cap file.
      If omitted, uses the currently loaded capture.
output_format: TOON
---

## Expert Info Skill

This skill runs `tshark -z expert -q -n` on a PCAP file and returns the
results as a TOON-formatted anomaly table (token-efficient, no JSON braces).

### What it detects

Wireshark's expert dissector pre-calculates the following categories:

| Severity | Examples |
|----------|---------|
| **Error** | TCP previous segment not captured, Malformed packet, Bad checksum |
| **Warning** | TCP retransmission, ACK of unseen segment, Window is full |
| **Note** | TCP keep-alive, Duplicate ACK, Window update |
| **Chat** | Connection established, Connection reset |

### Usage

Ask the agent any of the following:
- "Run tshark expert analysis on the current capture"
- "Check this PCAP for errors: /path/to/file.pcap"
- "What TCP issues are present in the capture?"
- "Show me all Wireshark warnings from the loaded file"

### Tool invocation

```
TOOL: tshark_expert
TOOL: tshark_expert /absolute/path/to/capture.pcap
```

### Token optimization

Output is TOON-formatted:
```
EXPERT_INFO[12]
severity group protocol summary count
Error Sequence TCP Previous_segment_not_captured 3
Warn Sequence TCP Retransmission 7
Note Sequence TCP Duplicate_ACK 15
```

This is 40-60% fewer tokens than equivalent JSON output.

### Integration with other tools

After running `tshark_expert`, feed the results to:
- `expert_analyze ics_audit` — deeper ICS-specific analysis
- `tshark_filter "retransmission"` — get the display filter to drill down
- `dnp3_analyze` — if DNP3 warnings are present
- `modbus_analyze` — if Modbus errors are present
