---
name: packet-forensics
description: >
  Deep analysis of packet capture files (PCAP/PCAPNG): protocol breakdown,
  expert anomaly detection, conversation reconstruction, and export. Use when
  user wants to analyze a PCAP file, loaded capture, packet data, or asks
  what's in the traffic, protocol statistics, or expert analysis.
license: Proprietary
compatibility: Requires tshark (Wireshark)
metadata:
  category: packet-analysis
  triggers:
    - pcap
    - pcapng
    - capture file
    - analyze traffic
    - what protocols
    - expert analysis
    - packet analysis
    - wireshark
    - tshark
    - dissect
    - decode
    - conversation
  tool_sequence:
    - tshark_expert
    - query_packets
    - expert_analyze flow_analysis
    - expert_analyze conversations
    - generate_insight general
  examples:
    - "Analyze this PCAP file"
    - "What protocols are in the capture?"
    - "Run expert analysis on the loaded traffic"
    - "Show me the conversations in the capture"
    - "What anomalies are in the PCAP?"
---

## Packet Forensics Workflow

### Standard PCAP analysis sequence
1. `tshark_expert [pcap]` — Wireshark's built-in expert: TCP errors, retransmissions, malformed packets, protocol warnings. Always run this first — it's fast and surfaces the most obvious issues.
2. `query_packets [proto] [n]` — sample specific protocols or recent packets for detail review
3. `expert_analyze flow_analysis` — conversation-level stats (bytes, packets per flow)
4. `expert_analyze conversations` — reconstruct TCP/UDP session pairs
5. `generate_insight general` — LLM-generated traffic summary

### When to use which tool
| Goal | Tool |
|---|---|
| Quick anomaly check | `tshark_expert` |
| See all Modbus commands | `modbus_forensics <pcap>` |
| See all DNP3 control ops | `dnp3_forensics <pcap>` |
| Filter by protocol | `query_packets TCP 30` |
| Check for threats | `expert_analyze anomaly_detect` |
| ICS security audit | `expert_analyze ics_audit` |
| Generate display filter | `tshark_filter <description>` |

### Interpreting tshark_expert output
- **Error (red)**: TCP retransmissions, duplicate ACKs, zero window — network or application issue
- **Warning (yellow)**: Out-of-order packets, deprecated protocols
- **Note (cyan)**: Protocol quirks, informational
- **Chat (grey)**: Normal session events (SYN, FIN)

High error counts relative to total packet count indicate network degradation.
