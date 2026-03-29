---
name: tshark
version: "1.0"
description: >
  Full tshark CLI reference for live packet capture, display filter generation,
  and expert analysis. Covers BPF capture filters, Wireshark display filter syntax,
  field extraction, file rotation, and ICS/SCADA capture recipes. Chain capture →
  tshark_filter → tshark_expert for deep traffic analysis.
triggers:
  - "tshark"
  - "packet capture"
  - "capture traffic"
  - "live capture"
  - "pcap"
  - "start capture"
  - "stop capture"
  - "interface list"
tools:
  - capture
  - tshark_filter
  - tshark_expert
parameters:
  duration:
    type: integer
    required: false
    description: Capture duration in seconds (default 10)
  interface:
    type: string
    required: false
    description: Network interface name (e.g. eth0, Ethernet, Wi-Fi)
  filter:
    type: string
    required: false
    description: BPF capture filter expression
output_format: TOON (token-optimized notation) — concise structured text
---

## Tshark Capture Skill

### What tshark Is

tshark is the command-line version of Wireshark. It captures live packets from a
network interface or reads existing PCAP files and decodes hundreds of protocols
including Modbus TCP, DNP3, EtherNet/IP, S7, IEC 60870-5-104, and all standard
IT protocols.

Use tshark when you need to:
- Capture live traffic on a specific interface
- Filter traffic by protocol, IP, port, or any field
- Perform expert analysis on a PCAP file
- Extract specific fields for scripting or reporting

---

### Starting and Stopping a Capture

The `capture` tool wraps tshark for live capture. Default duration is 10 seconds.

```
TOOL: capture
TOOL: capture 30
TOOL: capture 60
```

Optionally specify an interface and BPF filter (if the backend supports extended args):

```
TOOL: capture 30 eth0
TOOL: capture 15 "Ethernet 2"
```

The capture result is stored in memory and can be immediately passed to
`tshark_filter` or `tshark_expert`.

---

### Listing Network Interfaces

Before capturing, identify available interfaces:

| Platform | Command |
|----------|---------|
| Windows  | `tshark -D` |
| Linux    | `tshark -D` or `ip link show` |
| macOS    | `tshark -D` |

Example output:
```
1. \Device\NPF_{GUID} (Ethernet)
2. \Device\NPF_Loopback (Adapter for loopback traffic capture)
3. \Device\NPF_{GUID2} (Wi-Fi)
```

Use the number or quoted name with `-i`:
```
tshark -i 1 -w capture.pcap
tshark -i "Ethernet" -w capture.pcap
```

---

### BPF Capture Filters

BPF (Berkeley Packet Filter) filters are evaluated in the kernel — very fast.
Apply at capture time with `-f "expression"`.

| Expression | Captures |
|-----------|---------|
| `host 192.168.1.10` | All traffic to/from that host |
| `net 192.168.1.0/24` | Entire subnet |
| `port 502` | Modbus TCP |
| `port 20000` | DNP3 |
| `port 102` | S7comm (Siemens) |
| `port 44818` | EtherNet/IP |
| `tcp` | TCP only |
| `udp` | UDP only |
| `not port 22` | Exclude SSH |
| `host 10.0.0.1 and port 502` | Modbus to specific PLC |
| `net 10.0.0.0/8 and tcp port 502` | Modbus on OT subnet |

Compound filters use `and`, `or`, `not` (or `&&`, `||`, `!`).

---

### Display Filter Syntax

Display filters are applied after capture (in tshark: `-Y "expression"`). More
expressive than BPF — can filter on any decoded field.

**IP and Transport:**
```
ip.addr == 192.168.1.10
ip.src == 10.0.0.1
ip.dst == 192.168.1.100
tcp.port == 502
udp.port == 20000
tcp.flags.syn == 1
tcp.flags.reset == 1
```

**ICS Protocols:**
```
modbus
modbus.func_code == 3          # Read Holding Registers
modbus.func_code >= 128        # Exception responses (FC + 0x80)
modbus.exception_code == 2     # Illegal Data Address
dnp3
s7comm
enip
```

**Errors and Anomalies:**
```
tcp.analysis.retransmission
tcp.analysis.lost_segment
tcp.analysis.zero_window
icmp.type == 3                 # Destination Unreachable
```

**Time-based slicing:**
```
frame.time_relative >= 10.0 and frame.time_relative <= 20.0
```

Use the `tshark_filter` tool to generate a display filter from natural language:

```
TOOL: tshark_filter modbus exception frames only
TOOL: tshark_filter all tcp resets in the last 30 seconds
TOOL: tshark_filter traffic between 192.168.1.10 and 192.168.1.20
```

---

### Field Extraction with -T fields

Extract specific fields as tab-separated text for scripting:

```bash
tshark -r capture.pcap -T fields \
  -e frame.number \
  -e frame.time_relative \
  -e ip.src \
  -e ip.dst \
  -e tcp.srcport \
  -e tcp.dstport \
  -e modbus.func_code \
  -E header=y -E separator=,
```

Useful field names:
- `frame.len` — packet length in bytes
- `eth.src` / `eth.dst` — MAC addresses
- `ip.ttl` — TTL (useful for OS fingerprinting)
- `tcp.stream` — TCP stream index (group related packets)
- `modbus.data` — raw Modbus data bytes
- `dnp3.ctl.dir` — DNP3 direction bit

---

### File Rotation

For long-duration captures, rotate files to avoid single large PCAPs:

```bash
# Rotate every 100 MB, keep 5 files
tshark -i eth0 -b filesize:102400 -b files:5 -w capture.pcap

# Rotate every 60 seconds, keep 10 files
tshark -i eth0 -b duration:60 -b files:10 -w capture.pcap
```

The output files are named `capture_00001_YYYYMMDDHHMMSS.pcap`.

---

### Expert Analysis

The `tshark_expert` tool runs tshark's built-in expert analysis on the most
recent capture or a named PCAP and returns a structured summary:

```
TOOL: tshark_expert
TOOL: tshark_expert /path/to/capture.pcap
```

Expert analysis detects:
- TCP retransmissions and out-of-order segments
- Duplicate ACKs indicating congestion
- Zero-window stalls (receiver buffer full)
- Application-layer errors (Modbus exceptions, HTTP 5xx)
- Malformed packets and dissector warnings

---

### Recommended Workflow: capture → filter → expert

For any traffic analysis task, follow this chain:

1. **Capture** — gather raw traffic for a defined window
   ```
   TOOL: capture 30
   ```

2. **Filter** — isolate the relevant protocol or anomaly
   ```
   TOOL: tshark_filter Modbus write commands only
   ```

3. **Expert analysis** — get a structured diagnosis
   ```
   TOOL: tshark_expert
   ```

4. **Modbus deep-dive** (if ICS) — parse register-level details
   ```
   TOOL: modbus_analyze /tmp/latest_capture.pcap
   ```

---

### Common ICS Capture Recipes

**Monitor all Modbus traffic on the OT network:**
```bash
tshark -i eth0 -f "port 502" -Y "modbus" -T fields \
  -e ip.src -e ip.dst -e modbus.func_code -e modbus.reference_num \
  -E header=y
```

**Capture DNP3 with timestamps:**
```bash
tshark -i eth0 -f "port 20000" -t ad -w dnp3_session.pcap
```

**Watch for Modbus exception responses in real time:**
```bash
tshark -i eth0 -f "port 502" -Y "modbus.func_code >= 128" \
  -T fields -e ip.src -e modbus.exception_code
```

**Baseline scan — all unique IP pairs:**
```bash
tshark -r capture.pcap -q -z conv,ip
```

**Protocol hierarchy summary:**
```bash
tshark -r capture.pcap -q -z io,phs
```

---

### Output Format (TOON)

When reporting tshark results, use token-optimized notation:

```
CAPTURE: 30s | iface=eth0 | pkts=4821 | bytes=3.1MB
PROTO_MIX: Modbus/TCP 68% | HTTP 12% | ARP 9% | Other 11%
MODBUS_SUMMARY: reads=312 writes=28 exceptions=4
ANOMALIES: 3 retransmissions | 1 zero-window | 0 resets
TOP_TALKERS: 192.168.1.10→192.168.1.20 (2.1MB) | 192.168.1.10→192.168.1.21 (0.8MB)
```
