---
name: network-diagnostics
version: "1.0"
description: >
  Ping, traceroute, ARP, and connectivity troubleshooting for IT and ICS networks.
  Covers RTT interpretation, packet loss diagnosis, hop-by-hop route analysis,
  ARP cache inspection, MTU discovery, and SCADA-specific latency expectations
  for Modbus TCP polling intervals.
triggers:
  - "ping"
  - "traceroute"
  - "tracert"
  - "arp"
  - "dns lookup"
  - "network latency"
  - "packet loss"
  - "connectivity test"
  - "unreachable"
  - "route"
  - "hop count"
  - "gateway"
  - "name resolution"
tools:
  - ping
  - tracert
  - arp
  - capture
  - tshark_filter
parameters:
  host:
    type: string
    required: false
    description: Target hostname or IP address
output_format: RTT table + route table + ARP table
---

## Network Diagnostics Skill

### Tool Overview

Three tools cover the core connectivity diagnostics workflow:

| Tool | Purpose | Key Output |
|------|---------|-----------|
| `ping` | Reachability + RTT | Min/Avg/Max latency, packet loss % |
| `tracert` | Route path + per-hop latency | Hop-by-hop RTT and IP addresses |
| `arp` | LAN MAC-to-IP mapping | ARP cache table |

---

### Ping

```
TOOL: ping 192.168.1.10
TOOL: ping 8.8.8.8
TOOL: ping plc-01.lan
```

**Interpreting ping output:**

```
Pinging 192.168.1.10 with 32 bytes of data:
Reply from 192.168.1.10: bytes=32 time=2ms TTL=64
Reply from 192.168.1.10: bytes=32 time=1ms TTL=64
Reply from 192.168.1.10: bytes=32 time=3ms TTL=64
Reply from 192.168.1.10: bytes=32 time=2ms TTL=64

Ping statistics for 192.168.1.10:
    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss)
Approximate round trip times in milli-seconds:
    Minimum = 1ms, Maximum = 3ms, Average = 2ms
```

| Field | What It Tells You |
|-------|--------------------|
| `time=Nms` | Round-trip time — lower is better |
| `TTL=N` | Time-to-live; decrements per hop. TTL=64 = Linux/ICS, TTL=128 = Windows |
| `Lost = 0 (0%)` | No packet loss — healthy |
| `Request timed out` | Host unreachable or ICMP blocked |
| `Destination host unreachable` | No route to host (sent by gateway) |

**RTT benchmarks:**

| Network | Expected RTT | Investigation Threshold |
|---------|-------------|------------------------|
| Same LAN switch | < 1 ms | > 5 ms |
| LAN across routers | 1–5 ms | > 20 ms |
| WAN / VPN | 20–100 ms | > 200 ms |
| Intercontinental | 100–300 ms | > 500 ms |

**Packet loss interpretation:**
- 0% — Healthy
- 1–5% — Minor congestion or marginal link quality
- 5–25% — Significant issue; investigate switch/cable/interface
- >25% — Severe degradation; link may be failing
- 100% — Host down, firewalled, or route missing

---

### Tracert / Traceroute

```
TOOL: tracert 192.168.1.100
TOOL: tracert 8.8.8.8
TOOL: tracert plc-gateway.lan
```

**Reading tracert output:**

```
Tracing route to 192.168.1.100 over a maximum of 30 hops:

  1    <1 ms    <1 ms    <1 ms  192.168.0.1      ← Default gateway
  2     2 ms     2 ms     2 ms  10.0.0.1         ← Core switch / L3
  3     3 ms     3 ms     4 ms  10.1.0.1         ← OT DMZ router
  4     5 ms     4 ms     5 ms  192.168.1.100    ← Target PLC

Trace complete.
```

| Symbol | Meaning |
|--------|---------|
| `<1 ms` | Sub-millisecond — local device |
| `* * *` | Hop does not respond to ICMP (firewall or router config) — not always an error |
| `!H` | Host unreachable |
| `!N` | Network unreachable |
| `!P` | Protocol unreachable |
| `!F` | Fragmentation needed but DF bit set |

**Identifying bottlenecks:**
- Sudden RTT jump at a specific hop (e.g., hop 3 goes from 2ms to 80ms) — bandwidth-limited or congested link between hops 2 and 3
- All hops after a `* * *` respond normally — firewall drops ICMP TTL-exceeded but allows traffic through (benign)
- All hops after a `* * *` also show `* * *` — route blackhole or link failure

**Route asymmetry:**
- Traceroute from A→B and B→A may show different paths (common with ECMP and BGP)
- If one direction has high latency and the other doesn't, the problem is on the return path

---

### ARP

```
TOOL: arp
```

**ARP table format (Windows `arp -a`):**

```
Interface: 192.168.1.10 --- 0x3
  Internet Address      Physical Address      Type
  192.168.1.1           00-11-22-33-44-55     dynamic
  192.168.1.20          aa-bb-cc-dd-ee-ff     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
```

| Column | Meaning |
|--------|---------|
| Internet Address | IPv4 address of the neighbor |
| Physical Address | MAC (hardware) address |
| Type | `dynamic` = learned via ARP; `static` = manually configured |

**ARP spoofing indicators:**
- Two different IPs mapping to the same MAC address:
  ```
  192.168.1.1   aa:bb:cc:dd:ee:ff  ← Gateway
  192.168.1.10  aa:bb:cc:dd:ee:ff  ← SAME MAC — attacker spoofing gateway
  ```
- The same IP appearing with a suddenly different MAC compared to a previous baseline
- A legitimate device IP pointing to a broadcast or multicast MAC (ff:ff:ff:ff:ff:ff for a unicast IP)

**Gratuitous ARP:**
A gratuitous ARP is an unsolicited ARP reply where a host announces its own
IP-to-MAC mapping to the LAN. Legitimate uses: IP conflict detection, failover
(HSRP/VRRP), device boot. Suspicious uses: ARP poisoning (attacker overwrites
the cache of all hosts to redirect traffic through themselves).

Detection in packet capture:
```
TOOL: tshark_filter gratuitous ARP packets
```

---

### Diagnosing Common Issues

**High latency (RTT elevated but no packet loss):**
1. Run `tracert` — find which hop introduces the delay
2. Check that switch interface for errors: duplex mismatch is a common cause (<1ms becomes 5-10ms)
3. Check CPU utilization on the router at that hop
4. If it's only to ICS devices: verify Modbus polling rate is not too high for device capability

**Packet loss (intermittent):**
1. Run extended ping: `ping -n 100 <host>` (Windows) or `ping -c 100 <host>` (Linux)
2. If loss is consistent, check physical layer: cable, SFP module, switch port counters
3. If loss is random, check for duplex mismatch (half-duplex forced on one end)
4. Capture with tshark and look for `tcp.analysis.retransmission`

**Host unreachable (no replies at all):**
1. Verify host is powered on
2. Check gateway ARP entry: `arp -a | grep <gateway_ip>`
3. If gateway ARP is missing, DHCP may have failed — check `ipconfig` / `ip addr`
4. If on different subnet: verify routing table with `route print` (Windows) / `ip route` (Linux)

**DNS resolution failure:**
```
TOOL: ping hostname.domain.local
```
If ping by hostname fails but ping by IP works → DNS issue, not connectivity.
Check DNS server config with `TOOL: ipconfig` (see DNS Servers field).

---

### MTU and Fragmentation

MTU (Maximum Transmission Unit) mismatches cause intermittent failures, especially
over VPNs and WAN links. A large packet gets silently dropped if the DF (Don't
Fragment) bit is set.

**Testing MTU on Windows:**
```
ping -f -l 1472 192.168.1.1   # Test 1472 bytes (1500 - 20 IP - 8 ICMP = 1472)
ping -f -l 1400 192.168.1.1   # If 1472 fails, try smaller sizes
```

**Testing MTU on Linux:**
```bash
ping -M do -s 1472 192.168.1.1
```

If the large ping fails but small ping succeeds → MTU mismatch.
Reduce MTU on the interface:
```bash
ip link set eth0 mtu 1400
```

In tracert output, `!F` (fragmentation needed) at a hop confirms MTU mismatch at that point.

---

### ICS-Specific Latency Considerations

Modbus TCP is a request-response protocol. The SCADA master polls each slave
sequentially. RTT directly determines how fast the polling cycle completes.

**Modbus TCP RTT expectations:**

| Path | Expected RTT | Max Acceptable |
|------|-------------|---------------|
| Master → PLC (same LAN) | < 2 ms | 5 ms |
| Master → PLC (L3 hop) | 2–10 ms | 20 ms |
| Master → Remote RTU (WAN) | 20–100 ms | 200 ms |
| Master → Cloud-connected device | 50–200 ms | 500 ms |

**Why latency matters in SCADA:**
- A 500ms poll cycle for 100 devices = 50 seconds per scan cycle
- At 5ms per device, the same 100 devices scan in 500ms
- High RTT causes SCADA historians to miss samples and triggers false alarms

**Rule:** If `ping <plc>` shows RTT > 10ms on a local network, investigate before
assuming it is a Modbus communication issue.

---

### Recommended Workflow: Full Connectivity Audit

```
TOOL: ping 192.168.1.10
```
→ Is the host reachable? What is the RTT?

```
TOOL: tracert 192.168.1.10
```
→ How many hops? Where is latency introduced?

```
TOOL: arp
```
→ Is the MAC address correct? Any duplicate MACs?

If issues found, chain with packet capture:
```
TOOL: capture 30
TOOL: tshark_filter retransmissions and latency issues
TOOL: tshark_expert
```
