---
name: nmap
version: "1.0"
description: >
  Network host discovery and port scanning with ICS/SCADA safety guidance.
  Covers nmap scan types, timing templates, ICS-specific NSE scripts, output
  formats, and safe scanning practices for operational technology networks.
  Uses modbus_scan for safe Modbus-specific discovery.
triggers:
  - "nmap"
  - "port scan"
  - "host discovery"
  - "service detection"
  - "open ports"
  - "network scan"
  - "scan subnet"
  - "discover hosts"
  - "modbus discover"
  - "nse script"
tools:
  - modbus_scan
parameters:
  target:
    type: string
    required: false
    description: IP address, CIDR subnet, or hostname to scan
  timing:
    type: string
    required: false
    description: Timing template T0-T5 (default T2 for OT networks)
output_format: JSON summary + port table
---

## Nmap Scan Skill

### What nmap Is

nmap (Network Mapper) is the industry-standard open-source tool for network
discovery and security auditing. It determines what hosts are up, what ports are
open, what services are running, and (optionally) what OS a host is running.

**CRITICAL SAFETY WARNING FOR ICS/OT NETWORKS:**
> Aggressive nmap scans (-T4, -T5, -A, -sS without care) can crash or lock up
> PLCs, RTUs, HMIs, and other industrial devices that have fragile TCP stacks.
> Always use -T1 or -T2 on live operational networks. Never run -A or --script
> vulnerability scans against production ICS equipment without written approval.

---

### Scan Types

| Flag | Type | Description |
|------|------|-------------|
| `-sn` | Ping sweep | Host discovery only, no port scan |
| `-sS` | SYN scan | Half-open TCP (stealthy, requires root) |
| `-sT` | TCP connect | Full TCP handshake (no root needed) |
| `-sU` | UDP scan | UDP port scan (slow — be patient) |
| `-sV` | Version detection | Probe open ports to determine service/version |
| `-sC` | Script scan | Run default NSE scripts |
| `-O`  | OS detection | OS fingerprinting via TCP/IP stack analysis |
| `-A`  | Aggressive | Enables -sV, -sC, -O, and traceroute |

For ICS networks, prefer `-sT -sV` over `-sS` — some managed switches block
half-open connections or log them as attacks.

---

### Timing Templates

| Template | Name | Delay | Use Case |
|----------|------|-------|---------|
| `-T0` | Paranoid | 5 min between probes | IDS evasion |
| `-T1` | Sneaky | 15 s between probes | **Recommended for live ICS** |
| `-T2` | Polite | 0.4 s between probes | **Safe for most OT networks** |
| `-T3` | Normal | Adaptive | Default, IT networks only |
| `-T4` | Aggressive | Very fast | **DO NOT USE on ICS** |
| `-T5` | Insane | No delay | **NEVER use on ICS** |

**Rule of thumb:** Use `-T2` for any network with PLCs, RTUs, HMIs, or
historian servers. Use `-T1` if devices are known to be fragile.

---

### ICS-Specific NSE Scripts

nmap's Nmap Scripting Engine (NSE) includes scripts for industrial protocols:

| Script | Protocol | Port | What It Does |
|--------|---------|------|-------------|
| `modbus-discover` | Modbus TCP | 502 | Enumerates unit IDs 1-247 |
| `s7-info` | S7comm (Siemens) | 102 | Reads PLC identity block |
| `bacnet-info` | BACnet | 47808 | Reads device object properties |
| `enip-info` | EtherNet/IP | 44818 | Reads CIP identity object |
| `dnp3-info` | DNP3 | 20000 | Basic DNP3 link-layer probe |
| `iec-identify` | IEC 60870-5-104 | 2404 | Station interrogation |

**Usage examples:**
```bash
# Modbus device enumeration (safe, read-only)
nmap -sT -p 502 --script modbus-discover -T2 192.168.1.0/24

# Siemens S7 identity
nmap -sT -p 102 --script s7-info -T2 10.0.1.50

# EtherNet/IP scan
nmap -sT -p 44818 --script enip-info -T2 192.168.0.0/24

# BACnet/UDP (requires UDP scan)
nmap -sU -p 47808 --script bacnet-info -T2 192.168.1.0/24
```

---

### Output Formats

| Flag | Format | File Extension | Use Case |
|------|--------|---------------|---------|
| `-oN file` | Normal text | `.nmap` | Human reading |
| `-oX file` | XML | `.xml` | Tool integration, import to Nessus |
| `-oG file` | Grepable | `.gnmap` | grep/awk post-processing |
| `-oA prefix` | All three | `.nmap/.xml/.gnmap` | Save everything |

Always save nmap output for documentation:
```bash
nmap -sT -sV -T2 -oA scan_results 192.168.1.0/24
```

---

### Common Scan Recipes

**1. Fast host discovery (no port scan):**
```bash
nmap -sn -T2 192.168.1.0/24
```

**2. Standard ICS subnet sweep (safe):**
```bash
nmap -sT -p 21,22,23,80,102,443,502,503,1911,2404,4000,20000,44818,47808 \
  -T2 -oA ics_sweep 192.168.1.0/24
```

**3. Service version on specific host:**
```bash
nmap -sT -sV -p- -T2 192.168.1.100
```

**4. OS fingerprinting (non-invasive):**
```bash
nmap -O --osscan-guess -T2 192.168.1.100
```

**5. Full ICS script scan (test environment only):**
```bash
nmap -sT -sV --script "modbus-discover,s7-info,enip-info,bacnet-info" \
  -T2 -oA ics_full_scan 10.0.0.0/24
```

**6. UDP scan for SNMP and BACnet:**
```bash
nmap -sU -p 161,162,47808 -T2 192.168.1.0/24
```

---

### Modbus-Specific Discovery with modbus_scan

The agent has a native `modbus_scan` tool that is safer than nmap for Modbus
discovery — it sends standard Modbus read requests and parses responses without
the overhead of a full port scan engine.

```
TOOL: modbus_scan 192.168.1.0/24
TOOL: modbus_scan 10.0.0.1,10.0.0.2,10.0.0.10
```

Use `modbus_scan` when:
- You only need to find Modbus devices (port 502)
- You want register-level confirmation a device is responding
- The network has sensitive PLCs that could react badly to nmap probes

Use `nmap modbus-discover` when:
- You need to enumerate all 247 unit IDs on each device
- You want combined output with other protocol scans
- You are scanning a test/lab environment

---

### Interpreting Nmap Results

**Port states:**

| State | Meaning |
|-------|---------|
| `open` | Application is actively accepting connections |
| `closed` | Port reachable, no application listening |
| `filtered` | Firewall blocking — nmap cannot determine state |
| `open\|filtered` | Cannot distinguish (common with UDP) |
| `unfiltered` | Reachable but state undetermined (ACK scan result) |

**Key fields in output:**
- `VERSION` line — service banner, software version (e.g., `Modbus/TCP Schneider Electric`)
- `OS DETECTION` — TTL, window size, and option fingerprint used to guess OS
- `SCRIPT OUTPUT` — NSE script results (Modbus unit IDs, S7 CPU type, etc.)

**Red flags in ICS scan results:**
- Port 23 (Telnet) open on a PLC — plaintext management, high risk
- Port 21 (FTP) open on historian — credentials in the clear
- Unexpected SSH (port 22) on an HMI — may indicate compromise
- Modbus unit IDs that were not in the device inventory — unauthorized device

---

### Safety Checklist Before Scanning ICS Networks

- [ ] Written approval from the asset owner or plant manager
- [ ] Maintenance window scheduled (scan during low-production hours)
- [ ] Timing set to -T1 or -T2
- [ ] No vulnerability scripts (-script vuln) in scope
- [ ] Backup engineer monitoring DCS/SCADA historian
- [ ] Rollback plan if a device crashes (known last-good config)
- [ ] Output saved and handed to asset owner after the engagement
