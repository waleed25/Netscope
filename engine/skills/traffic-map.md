---
name: traffic-map
description: >
  Visualize and analyze network traffic topology: which hosts are communicating,
  traffic volumes, protocol distribution, and external vs internal hosts.
  Use when the user asks about traffic maps, network topology, host graphs,
  who is talking to whom, or wants to open/show the Traffic Map tab.
license: Proprietary
metadata:
  category: visualization
  triggers:
    - traffic map
    - trafficmap
    - open map
    - show map
    - topology
    - host graph
    - network graph
    - who is talking
    - who's talking
    - hosts and flows
    - flow map
    - network topology
    - ip graph
    - communication map
    - traffic visualization
    - visualize traffic
    - open traffic map
    - traffic tab
    - node graph
  tool_sequence:
    - traffic_map_summary
  examples:
    - "Show me the traffic map"
    - "Who is talking to who?"
    - "Open the traffic map"
    - "What hosts are on the network?"
    - "Show me a topology of the traffic"
    - "Which hosts have the most traffic?"
    - "Are there any external IPs communicating?"
output_format: >
  Present the topology as a structured summary: total hosts, total flows,
  top talkers table (IP, packets, bytes, protocols, internal/external),
  top flows table (src → dst, packets, protocols), and a list of external IPs.
  Mention that the visual Traffic Map tab has been opened for an interactive view.
---

## Traffic Map Skill

Use `traffic_map_summary` to retrieve the current network topology from captured packets.
The tool returns structured JSON — use it to answer questions about:

- **Which hosts are most active** (top talkers by packet/byte count)
- **Which IPs are communicating** (flow pairs: src → dst)
- **External vs internal hosts** (public IPs vs RFC-1918 ranges)
- **Protocol distribution** (TCP, UDP, ICMP, DNS, HTTP, TLS, Modbus…)

### Output format

Present results as two tables and a summary paragraph:

**Top Hosts** table:
| IP | Packets | Bytes | Protocols | Type |
|---|---|---|---|---|

**Top Flows** table:
| Source | Destination | Packets | Protocols |
|---|---|---|---|

Then a short paragraph highlighting:
- Any external IPs and what they're doing
- Any unusual protocols or high-volume flows
- Whether the capture looks like normal traffic or anomalous activity

### Notes
- The Traffic Map tab opens automatically when this tool is called (interactive visualization)
- `traffic_map_summary [N]` accepts an optional limit (default 10, max 50)
- Call `query_packets` afterwards if you need per-packet detail on a specific host
