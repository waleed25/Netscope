---
name: threat-hunting
description: >
  Hunt for network threats, C2 beaconing, lateral movement, port scans,
  ARP spoofing, DNS tunneling, and anomalous traffic patterns. Use when
  user asks about threats, attacks, intrusions, malware, C2, beaconing,
  lateral movement, reconnaissance, suspicious traffic, or security incidents.
license: Proprietary
metadata:
  category: threat-detection
  triggers:
    - threat
    - attack
    - intrusion
    - malware
    - c2
    - command and control
    - beaconing
    - lateral movement
    - reconnaissance
    - port scan
    - arp spoof
    - dns tunnel
    - suspicious
    - anomaly
    - security incident
    - ioc
    - indicator
  tool_sequence:
    - capture
    - expert_analyze anomaly_detect
    - expert_analyze port_scan
    - query_packets
    - generate_insight security
  examples:
    - "Is there any C2 beaconing in the capture?"
    - "Check for port scanning activity"
    - "Are there signs of lateral movement?"
    - "Look for ARP spoofing"
    - "Hunt for DNS tunneling"
    - "Any suspicious outbound connections?"
---

## Threat Hunting Workflow

### For live threat hunting
1. `capture 60` — collect a baseline (longer = better signal for beaconing)
2. `expert_analyze anomaly_detect` — statistical outliers, unusual flows
3. `expert_analyze port_scan` — sequential port/host sweep detection
4. `generate_insight security` — structured threat findings

### For captured PCAP analysis
1. `tshark_expert [pcap]` — built-in Wireshark expert: retransmissions, malformed packets, protocol errors
2. `query_packets 50` — sample recent packets for manual review
3. `expert_analyze flow_analysis` — conversation-level statistics

### Threat patterns to look for

**C2 Beaconing**: Regular outbound connections at fixed intervals (every 30/60/300s) to unusual external IPs. DNS queries to random-looking domains (DGA).

**Port Scanning**: Sequential `tcp.flags.syn == 1` packets from one source to many ports/hosts in short window. RST responses confirm closed ports.

**Lateral Movement**: SMB (445), RDP (3389), WinRM (5985/5986), or PsExec-like traffic between internal hosts. New internal-to-internal flows not seen in baseline.

**ARP Spoofing**: Multiple ARP replies for same IP from different MACs. Gratuitous ARPs followed by traffic redirection.

**DNS Tunneling**: Unusually long DNS queries (>100 chars), high-entropy subdomain labels, TXT record heavy traffic, or single domain receiving hundreds of queries.

**Data Exfiltration**: Large outbound transfers to unfamiliar destinations, especially after hours. Slow drips to avoid rate detection.

Report IOCs (IPs, domains, ports) and TTPs (MITRE ATT&CK techniques when applicable).
