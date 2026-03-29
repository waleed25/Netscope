---
name: filter-generation
version: "1.0"
description: >
  Dynamically generate correct tshark display filters from plain-language
  descriptions. Queries the knowledge base (RAG) for precise filter syntax,
  falls back to a curated built-in ICS/network filter reference.
triggers:
  - "tshark filter"
  - "display filter"
  - "wireshark filter"
  - "how to filter"
  - "filter for"
  - "show only"
  - "find packets"
  - "display filter syntax"
tools:
  - tshark_filter
  - rag_search
parameters:
  description:
    type: string
    required: true
    description: Plain-language description of what to filter (e.g. "modbus exceptions")
output_format: "FILTER: <expr>\nSOURCE: <rag|built-in>\nEXPLANATION: <text>"
---

## Filter Generation Skill

### Purpose

Generate correct `tshark -Y "<filter>"` display filter expressions from
plain-language descriptions without requiring users to memorize filter syntax.

### How It Works

1. **RAG query**: The skill searches the knowledge base (tshark manual,
   Wireshark wiki, bundled filter reference) for relevant filter syntax.

2. **Built-in fallback**: If RAG score is below threshold (0.30), uses a
   curated table of 35+ common ICS/network filters.

3. **Returns**: The filter expression, its source (RAG or built-in), and
   an explanation of what it matches.

### Example Queries

```
TOOL: tshark_filter modbus exceptions
→ FILTER: modbus.exception_code > 0
  SOURCE: built-in reference

TOOL: tshark_filter dnp3 direct operate
→ FILTER: dnp3.al.func == 0x05
  SOURCE: built-in reference

TOOL: tshark_filter tcp retransmissions
→ FILTER: tcp.analysis.retransmission
  SOURCE: built-in reference

TOOL: tshark_filter large packets over 1400 bytes
→ FILTER: frame.len > 1400
  SOURCE: built-in reference

TOOL: tshark_filter dns failures
→ FILTER: dns.flags.rcode != 0
  SOURCE: built-in reference
```

### Built-In Filter Categories

| Category | Example Query | Filter |
|----------|--------------|--------|
| Modbus reads | `modbus read` | `modbus.func_code <= 4` |
| Modbus writes | `modbus write` | `modbus.func_code >= 5 and modbus.func_code <= 6` |
| Modbus exceptions | `modbus exception` | `modbus.exception_code > 0` |
| DNP3 write | `dnp3 write` | `dnp3.al.func == 0x02` |
| DNP3 operate | `dnp3 operate` | `dnp3.al.func == 0x04` |
| TCP RST | `tcp reset` | `tcp.flags.reset == 1` |
| Retransmissions | `retransmission` | `tcp.analysis.retransmission` |
| DNS failures | `dns failure` | `dns.flags.rcode != 0` |
| HTTP errors | `http error` | `http.response.code >= 400` |
| All ICS | `ics scada` | `modbus or dnp3 or opcua or enip` |
| Broadcasts | `broadcast` | `eth.dst == ff:ff:ff:ff:ff:ff` |

### Applying Filters

After getting a filter expression, use it with tshark:

```bash
tshark -r capture.pcap -n -Y "modbus.exception_code > 0" \
  -T fields -E separator=, \
  -e frame.number -e ip.src -e ip.dst -e modbus.exception_code
```

Or in the agent, combine with capture analysis:

```
TOOL: tshark_filter modbus exceptions
TOOL: modbus_analyze /path/to/capture.pcap
```

### Enriching the Knowledge Base

Load the full tshark manual for richer RAG results:

```
POST /api/rag/seed-tshark
```

This ingests the bundled filter reference and crawls live Wireshark docs,
enabling the `tshark_filter` tool to return context-aware explanations from
the official documentation.
