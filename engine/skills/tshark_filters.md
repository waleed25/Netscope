---
name: tshark-filters
description: >
  Generate tshark and Wireshark display filter expressions for any protocol or
  traffic pattern. Use when user asks for a display filter, how to filter
  traffic, tshark syntax, Wireshark filter, BPF filter, or how to find specific
  packets using tshark command-line options.
license: Proprietary
compatibility: Requires tshark (Wireshark)
metadata:
  category: packet-analysis
  triggers:
    - display filter
    - tshark filter
    - wireshark filter
    - filter expression
    - filter syntax
    - how to filter
    - bpf
    - capture filter
    - tshark -Y
    - tshark -f
    - how do i find
  tool_sequence:
    - tshark_filter
    - rag_search
  examples:
    - "How do I filter Modbus exceptions in tshark?"
    - "Give me the display filter for TCP retransmissions"
    - "What's the tshark filter for DNP3 Write commands?"
    - "Filter only HTTP POST requests"
    - "Show me the syntax for TLS handshake filter"
---

## tshark Filter Generation Workflow

1. `tshark_filter <description>` — queries knowledge base first, falls back to built-in reference table
2. If result score is low, try `rag_search tshark display filter <protocol>` for richer context

### Quick reference: common patterns

```
# Protocol basics
modbus                          → modbus
dnp3                            → dnp3
tls                             → tls
dns                             → dns
http                            → http

# ICS/OT
modbus exceptions               → modbus.exception_code > 0
modbus writes                   → modbus.func_code >= 5 and modbus.func_code <= 6
dnp3 write/operate              → dnp3.al.func >= 2 and dnp3.al.func <= 6
dnp3 unsolicited                → dnp3.al.func == 0x82

# TCP analysis
retransmissions                 → tcp.analysis.retransmission
RST packets                     → tcp.flags.reset == 1
SYN flood                       → tcp.flags.syn == 1 and tcp.flags.ack == 0
zero window                     → tcp.analysis.zero_window

# Security
large packets                   → frame.len > 1400
broadcast                       → eth.dst == ff:ff:ff:ff:ff:ff
non-standard ports              → not (tcp.port in {80 443 22 25 53 8080})
```

### tshark command templates
```bash
# Filter + read PCAP
tshark -r capture.pcap -Y "modbus.exception_code > 0" -n

# Live capture with filter
tshark -i eth0 -f "port 502" -Y "modbus" -n

# Field extraction (TOON-compatible)
tshark -r capture.pcap -Y "modbus" -T fields -E separator=\t \
  -e frame.number -e ip.src -e modbus.func_code
```
