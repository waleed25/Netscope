---
name: netstat-ss
version: "1.0"
description: >
  Active connection and socket analysis using netstat (Windows) and ss (Linux).
  Covers TCP state interpretation, listening port identification, process-to-port
  mapping, detecting unexpected outbound connections, and ICS protocol port
  monitoring for Modbus, DNP3, S7comm, and EtherNet/IP.
triggers:
  - "netstat"
  - "active connections"
  - "listening ports"
  - "socket stats"
  - "established connections"
  - "tcp connections"
  - "udp sockets"
  - "who is connected"
  - "open sockets"
tools:
  - netstat
parameters:
  flags:
    type: string
    required: false
    description: Additional netstat flags (e.g. -ano, -rn)
output_format: connection table + anomaly summary
---

## Netstat / ss Skill

### Running the Tool

```
TOOL: netstat
```

The agent runs `netstat -ano` on Windows or `ss -tunap` on Linux and returns
the full socket table. The output is then analyzed for anomalies.

---

### Netstat Output Structure

**Windows `netstat -ano` columns:**

```
Proto  Local Address      Foreign Address    State        PID
TCP    0.0.0.0:502        0.0.0.0:0          LISTENING    1234
TCP    192.168.1.10:502   192.168.1.20:49152 ESTABLISHED  1234
UDP    0.0.0.0:20000      *:*                             5678
```

| Column | Meaning |
|--------|---------|
| Proto | TCP or UDP |
| Local Address | `IP:port` this machine is using |
| Foreign Address | `IP:port` of the remote end |
| State | Connection state (TCP only) |
| PID | Process ID owning the socket |

**Linux `ss -tunap` columns:**

```
Netid  State   Recv-Q  Send-Q  Local Address:Port  Peer Address:Port  Process
tcp    ESTAB   0       0       192.168.1.10:502    192.168.1.20:49152 users:(("modbusd",pid=1234))
tcp    LISTEN  0       128     0.0.0.0:22          0.0.0.0:*          users:(("sshd",pid=567))
```

---

### TCP State Machine

| State | Description | What to Look For |
|-------|-------------|-----------------|
| `LISTEN` | Server waiting for connections | Expected service ports only |
| `ESTABLISHED` | Active connection | Verify both endpoints are known |
| `TIME_WAIT` | Closed connection, timer running | High count = many short connections (normal for HTTP) |
| `CLOSE_WAIT` | Remote closed, local app hasn't | High count = application bug (not calling close()) |
| `SYN_SENT` | Client initiated, waiting for SYN-ACK | Long duration = unreachable host |
| `SYN_RECV` | Server got SYN, sent SYN-ACK | Many = SYN flood in progress |
| `FIN_WAIT_1/2` | Local side closing | Brief, should transition quickly |
| `LAST_ACK` | Waiting for final ACK after FIN | Very brief |

**Anomaly indicators:**
- Hundreds of `TIME_WAIT` on port 502 — Modbus master reconnecting too aggressively
- `CLOSE_WAIT` accumulation — memory leak risk, application not closing sockets
- `SYN_RECV` spike — potential SYN flood / DoS attack
- Long-lived `ESTABLISHED` connections from unknown foreign IPs — possible backdoor

---

### Common netstat Flags

**Windows:**

| Flag | Effect |
|------|--------|
| `-a` | Show all connections including LISTENING |
| `-n` | Numeric IPs and ports (no DNS resolution) |
| `-o` | Include PID for each connection |
| `-e` | Ethernet statistics |
| `-r` | Routing table |
| `-p tcp` | Filter to TCP only |
| `-p udp` | Filter to UDP only |
| `-b` | Show executable name (requires admin) |

Useful combinations:
```
netstat -ano              # All connections with PIDs
netstat -ano | findstr :502   # Filter to port 502
netstat -rn               # Routing table
netstat -e                # Bytes sent/received summary
```

**Linux ss equivalents:**

| ss Flag | Equivalent netstat | Effect |
|---------|-------------------|--------|
| `-t` | `-p tcp` | TCP only |
| `-u` | `-p udp` | UDP only |
| `-n` | `-n` | Numeric |
| `-a` | `-a` | All states |
| `-p` | `-b` | Show process |
| `-l` | (LISTEN filter) | Listening sockets only |
| `-s` | `-e` | Statistics summary |

```bash
ss -tunap                       # All TCP+UDP with processes
ss -tnap state established      # Only ESTABLISHED
ss -tlnp                        # Only listening TCP sockets
ss -tnap 'dport = :502'        # Connections to port 502
```

---

### Finding Which Process Owns a Port

**Windows (requires elevated prompt):**
```
netstat -ano | findstr :502
tasklist | findstr <PID>
```

Or in one step:
```
netstat -b -n | findstr -A 1 ":502"
```

**Linux:**
```bash
ss -tnap 'sport = :502'
lsof -i :502
fuser 502/tcp
```

---

### Detecting Unexpected Outbound Connections

Run `netstat` then look for ESTABLISHED connections where:
- Foreign address is on the internet (not RFC1918: 10.x, 172.16-31.x, 192.168.x)
- Local address is a server or OT device that should not initiate outbound
- Port is unusual (not 80, 443, 123 NTP)

**Specific patterns indicating compromise:**
```
TCP  192.168.1.50:49812  203.0.113.45:4444  ESTABLISHED  9999
                                      ^^^^        ^^^^
                               Internet IP    Unusual port — likely C2
```

For ICS devices (PLCs, HMIs, historians), any outbound ESTABLISHED connection
to an internet IP is suspicious and should be investigated immediately.

---

### ICS Protocol Port Reference

| Port | Protocol | Expected Devices |
|------|---------|-----------------|
| 502 | Modbus TCP | PLCs, inverters, meters, SCADA master |
| 503 | Modbus TLS | Secure Modbus (rare) |
| 2404 | IEC 60870-5-104 | RTUs, substation automation |
| 4000 | Emerson DeltaV | Distributed control system |
| 20000 | DNP3 over TCP | RTUs, power grid SCADA |
| 34980 | EtherNet/IP (UDP) | Allen-Bradley PLCs |
| 44818 | EtherNet/IP | Allen-Bradley PLCs, Rockwell |
| 102 | S7comm (ISO-TSAP) | Siemens SIMATIC PLCs |
| 1911 | Niagara Fox | Tridium BAS controllers |
| 47808 | BACnet/UDP | Building automation |
| 9600 | OMRON FINS | OMRON PLCs |

Check if these ports are LISTENING only on expected devices:
```
TOOL: netstat
```

Then ask: "Are there any devices listening on Modbus port 502 that are not in our device inventory?"

---

### Cross-Platform Summary

| Feature | Windows `netstat` | Linux `ss` | Linux `netstat` |
|---------|-------------------|-----------|----------------|
| Show PID | `-o` | `-p` | `-p` |
| Numeric output | `-n` | `-n` | `-n` |
| UDP sockets | `-p udp` | `-u` | `-u` |
| Routing table | `-r` | (use `ip route`) | `-r` |
| Socket stats | `-e` | `-s` | `-s` |
| Filter by port | `findstr :PORT` | `'sport = :PORT'` | `grep :PORT` |
| Speed | Moderate | Fast (kernel) | Moderate |

On modern Linux, `ss` is preferred — it queries the kernel directly and is
significantly faster on systems with thousands of sockets.

---

### Example Workflow: Full Connection Audit

```
TOOL: netstat
```

After getting output, analyze:
1. List all LISTENING ports — cross-reference with expected services
2. List all ESTABLISHED foreign IPs — flag any non-RFC1918 addresses
3. Count TIME_WAIT per port — flag >100 as potential storm
4. Check for CLOSE_WAIT accumulation — flag >10 as application issue
5. Map PIDs to process names — flag any unknown processes
6. Check ICS protocol ports (502, 20000, 102, 44818) — flag unexpected listeners
