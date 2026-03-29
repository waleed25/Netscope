---
name: live-capture
description: >
  Capture live network traffic, monitor real-time packets, and analyze active
  connections. Use when user wants to start a capture, sniff traffic, monitor
  the network live, record packets, or see what's happening on the wire right now.
license: Proprietary
compatibility: Requires tshark and a network interface
metadata:
  category: packet-analysis
  triggers:
    - capture
    - sniff
    - monitor
    - live traffic
    - start capturing
    - record packets
    - what's on the wire
    - live packets
    - real-time
  tool_sequence:
    - capture
    - query_packets
    - expert_analyze anomaly_detect
    - generate_insight general
  examples:
    - "Capture traffic for 30 seconds"
    - "Start monitoring the network"
    - "What traffic is happening right now?"
    - "Sniff for 1 minute and tell me what you see"
    - "Capture and look for any threats"
---

## Live Capture Workflow

### Basic capture
`capture [seconds]` — default 10s, max 120s. Automatically selects best available interface (prefers Ethernet/Wi-Fi over loopback).

### Capture + analysis
1. `capture 30` — collect traffic (30 seconds recommended for meaningful samples)
2. `query_packets 20` — review sample of captured packets
3. `expert_analyze anomaly_detect` — statistical anomaly detection on the capture
4. `generate_insight general` — summarize what was captured

### Capture + threat hunt
1. `capture 60` — collect baseline traffic
2. `expert_analyze port_scan` — check for scanning activity
3. `expert_analyze anomaly_detect` — behavioral anomalies
4. `generate_insight security` — threat-focused summary

### Important notes
- Only ONE capture can run at a time; a second `capture` call stops the first
- Packets accumulate in memory (max 5000); use `query_packets` to inspect subsets
- For ICS networks, use `expert_analyze ics_audit` after capture to check OT protocols
- tshark must be installed (part of Wireshark) for capture to work

### Duration guidelines
| Use case | Duration |
|---|---|
| Quick check | 10s |
| Normal analysis | 30s |
| Threat hunting | 60–120s |
| Beaconing detection | 120s (needs regular intervals) |
