---
name: network-diagnostics
description: >
  Diagnose network connectivity problems, slow connections, unreachable hosts,
  DNS failures, routing issues, and interface configuration. Use when user asks
  about connectivity, latency, slow network, can't reach a host, ping fails,
  DNS not resolving, route, gateway, or network configuration.
license: Proprietary
metadata:
  category: network-ops
  triggers:
    - connectivity
    - latency
    - slow
    - unreachable
    - can't reach
    - ping
    - dns
    - resolv
    - route
    - gateway
    - interface
    - ipconfig
    - network config
    - traceroute
    - tracert
    - arp cache
    - netstat
  tool_sequence:
    - ping
    - tracert
    - ipconfig
    - arp
    - netstat
  examples:
    - "I can't reach 8.8.8.8"
    - "Why is my network slow?"
    - "What's the route to 10.0.0.1?"
    - "Show me active connections"
    - "Check DNS resolution for google.com"
    - "What are my network interfaces?"
---

## Network Diagnostics Workflow

Follow this sequence — stop when the issue is found:

### Layer 1-2: Physical / ARP
- `ipconfig /all` — verify interface is up, IP assigned, gateway correct
- `arp -a` — check ARP table for gateway; missing entry = L2 problem

### Layer 3: IP Routing
- `ping <target>` — 4-packet ICMP test. Loss or RTT > 100ms on LAN = investigate
- `tracert <target>` — hop-by-hop path. First hop should be gateway. Where does it stop?

### Layer 4: Connections
- `netstat -ano` — all active TCP/UDP connections. Check for CLOSE_WAIT/TIME_WAIT backlog = server issue

### Layer 7: Application
- DNS: query packets for NXDOMAIN responses, high retry counts
- HTTP: check for 4xx/5xx in captured traffic

### Quick triage table
| Symptom | First tool | What to look for |
|---|---|---|
| Host unreachable | `ping` | Timeout vs TTL exceeded |
| Slow to specific host | `tracert` | High latency hop |
| DNS not working | `ping 8.8.8.8` then `ping google.com` | IP works but name fails |
| All connections slow | `netstat -ano` | Large ESTABLISHED count, many CLOSE_WAIT |
| Wrong subnet | `ipconfig /all` | Subnet mask mismatch |
| No gateway | `arp -a` | Missing gateway ARP entry |
