---
name: packet-ai-analysis
version: "1.0"
description: >
  AI-powered packet analysis workflows: quick traffic summaries, ICS protocol
  identification, expert security audits, anomaly detection, and flow analysis
  using the two-tier generate_insight / expert_analyze pipeline.
triggers:
  - "analyze traffic"
  - "ai analysis"
  - "packet insight"
  - "traffic summary"
  - "llm packet analysis"
  - "generate insight"
  - "expert analyze"
  - "ics audit"
  - "anomaly detect"
  - "flow analysis"
tools:
  - generate_insight
  - expert_analyze
  - query_packets
  - list_insights
  - capture
parameters:
  insight_mode:
    type: enum
    values: [general, ics_protocols, session_counts, response_time]
    description: "Mode for generate_insight"
  expert_mode:
    type: enum
    values: [ics_audit, port_scan, flow_analysis, conversations, anomaly_detect]
    description: "Mode for expert_analyze"
  filter:
    type: string
    description: "tshark-compatible display filter for query_packets"
output_format: TOON (Token-Optimized Object Notation) tables + Markdown
---

## Packet AI Analysis Skill

### Two-Tier Analysis System

Netscope provides two complementary analysis tools:

| Tool | Speed | Depth | Token Cost | Best For |
|------|-------|-------|------------|----------|
| `generate_insight` | Fast (5–15 s) | Overview | Low | Quick situational awareness |
| `expert_analyze` | Slower (15–60 s) | Deep | High | Security assessment, detailed audit |

Use `generate_insight` first to understand the traffic, then `expert_analyze`
for in-depth investigation of specific concerns.

### generate_insight Modes

#### General Traffic Summary

```
TOOL: generate_insight general
```

Produces a top-level overview: protocol distribution, top talkers, total packet
count, time range, and bandwidth summary. Start here for any unfamiliar capture.

#### ICS Protocol Identification

```
TOOL: generate_insight ics_protocols
```

Identifies industrial control system protocols present in the capture:
- Modbus TCP (port 502)
- DNP3 (port 20000)
- EtherNet/IP (port 44818)
- BACnet (port 47808)
- IEC 61850 GOOSE/MMS
- OPC-UA (port 4840)

Reports device addresses, function codes observed, and estimated device count.

#### Session Counts and Top Talkers

```
TOOL: generate_insight session_counts
```

Produces a ranked table of:
- Top source IPs by packet count
- Top destination IPs by byte volume
- Most active TCP/UDP conversations
- Unique host count and session count

#### Response Time Analysis

```
TOOL: generate_insight response_time
```

Measures request-response latency for detected protocols:
- Modbus: request → response RTT
- TCP: SYN → SYN-ACK RTT
- DNS: query → response RTT

Flags high-latency outliers (>500 ms for ICS is significant).

### expert_analyze Modes

#### ICS Security Audit

```
TOOL: expert_analyze ics_audit
```

Comprehensive industrial network security assessment:
- Unauthorized Modbus write operations (FC 5, 6, 15, 16)
- Devices communicating outside expected IP ranges
- Exception response rates (>5% indicates issues)
- Cleartext credentials or unencrypted engineering tool sessions
- Firmware upload traffic patterns

#### Port Scan Detection

```
TOOL: expert_analyze port_scan
```

Identifies scanning activity:
- Sequential port access from a single source
- SYN-only packets without completing handshakes
- ICMP sweeps
- Short-duration connection attempts to many hosts
- Known scanner tool signatures

#### Traffic Flow Analysis

```
TOOL: expert_analyze flow_analysis
```

Maps traffic patterns over time:
- Bandwidth utilization timeline
- Protocol mix changes
- Burst events and idle periods
- East-west vs north-south traffic ratio
- Multicast and broadcast volume

#### Conversation Matrix

```
TOOL: expert_analyze conversations
```

Produces a host-pair communication matrix showing:
- All unique source → destination pairs
- Byte and packet volumes per pair
- Protocol used per conversation
- Sessions that only communicate in one direction

#### Anomaly Detection

```
TOOL: expert_analyze anomaly_detect
```

Statistical anomaly detection:
- Hosts that appear only once in the capture (beaconing, recon)
- Unusually large individual packets (>1500 bytes on ICS networks)
- Protocol violations (malformed Modbus, invalid DNP3 addresses)
- Traffic at unusual hours (if timestamps span multiple days)
- New hosts not seen in baseline (if baseline exists)

### Querying Specific Packets

Before running expensive analysis, pre-filter the data:

```
TOOL: query_packets ip.src == 192.168.1.100
TOOL: query_packets modbus
TOOL: query_packets tcp.port == 502 and modbus.func_code == 6
TOOL: query_packets dns
```

Accepts tshark display filter syntax. Returns matching packets in TOON format.

### Viewing Stored Insights

```
TOOL: list_insights
```

Shows all insights generated in the current session with timestamps and modes.
Useful for reviewing earlier analysis results without re-running.

### Recommended Workflow

For a new capture or live traffic session:

```
1. TOOL: capture 30          ← capture 30 seconds of live traffic
2. TOOL: generate_insight general   ← get the overview
3. TOOL: generate_insight ics_protocols   ← identify ICS devices
4. TOOL: expert_analyze ics_audit   ← deep security check
5. TOOL: rag_search Modbus exception code 4   ← look up findings in KB
6. TOOL: list_insights              ← review all generated insights
```

For a PCAP file already loaded:

```
1. TOOL: generate_insight session_counts   ← understand traffic volume
2. TOOL: query_packets modbus.func_code == 6   ← check for writes
3. TOOL: expert_analyze anomaly_detect   ← flag statistical outliers
```

### Output Format: TOON

Analysis results use **TOON (Token-Optimized Object Notation)** — compact tables
instead of verbose JSON. This reduces token consumption by 40–60%.

Example TOON output:
```
PACKETS[5]
time       src             dst             proto  len
09:01:01   192.168.1.10   192.168.1.20   Modbus  66
09:01:01   192.168.1.20   192.168.1.10   Modbus  60
...
```

Compared to equivalent JSON, TOON preserves all data while fitting more records
within the context window. Ask explicitly for TOON output if responses are verbose.
