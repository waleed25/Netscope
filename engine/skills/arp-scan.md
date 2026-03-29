---
name: arp-scan
version: "1.0"
description: >
  LAN host discovery and ARP cache analysis for detecting all active hosts on
  a subnet, identifying ARP spoofing attacks, analyzing gratuitous ARP traffic,
  and monitoring ICS device MAC address changes. Uses the arp tool for cache
  inspection and guides use of arp-scan for active discovery.
triggers:
  - "arp scan"
  - "arp table"
  - "lan hosts"
  - "arp spoofing"
  - "mac address scan"
  - "arp cache"
  - "gratuitous arp"
  - "duplicate ip"
  - "who has ip"
tools:
  - arp
  - capture
  - tshark_filter
  - tshark_expert
parameters:
  interface:
    type: string
    required: false
    description: Network interface to scan (e.g. eth0, Ethernet)
  subnet:
    type: string
    required: false
    description: CIDR subnet to scan (e.g. 192.168.1.0/24)
output_format: host table (IP → MAC → OUI vendor) + anomaly list
---

## ARP Scan Skill

### What ARP Is

ARP (Address Resolution Protocol) maps IPv4 addresses to MAC addresses on a
local area network. When a host needs to send a packet to 192.168.1.10, it
broadcasts "Who has 192.168.1.10?" and the target replies with its MAC address.
The result is cached in the ARP table to avoid repeated broadcasts.

ARP has **no authentication** — any host can claim any IP address. This is the
fundamental weakness that ARP spoofing exploits.

---

### Reading the ARP Cache

```
TOOL: arp
```

The agent runs `arp -a` (Windows/Linux) and returns the complete ARP cache.

**Windows output format:**
```
Interface: 192.168.1.50 --- 0x3
  Internet Address      Physical Address      Type
  192.168.1.1           00-50-ba-85-85-ca     dynamic
  192.168.1.10          00-0c-29-1a-2b-3c     dynamic
  192.168.1.20          00-1a-4b-c8-73-f1     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static
  255.255.255.255       ff-ff-ff-ff-ff-ff     static
```

**Linux output format:**
```
Address                  HWtype  HWaddress           Flags Iface
192.168.1.1              ether   00:50:ba:85:85:ca   C     eth0
192.168.1.10             ether   00:0c:29:1a:2b:3c   C     eth0
192.168.1.20             ether   00:1a:4b:c8:73:f1   C     eth0
```

| Column | Meaning |
|--------|---------|
| IP Address | IPv4 address of the neighbor |
| Physical/HWaddress | Ethernet MAC (48-bit hardware address) |
| Type / Flags | `dynamic` = learned via ARP; `static` = manually set; `C` = cache |
| Interface | Which local adapter learned this entry |

---

### ARP Table Analysis: What to Look For

**1. All hosts on the subnet**
Every device that has communicated recently will be in the cache. Compare against
your expected device inventory. Unexpected IPs indicate unauthorized devices.

**2. Gateway MAC address**
The default gateway (router) entry is the most important. Any unexpected change
in the gateway's MAC is a strong indicator of ARP spoofing.

**3. Multicast/broadcast entries (normal)**
- `224.0.0.x` → Multicast group address (OSPF, mDNS, etc.)
- `ff-ff-ff-ff-ff-ff` → Broadcast (normal)
- `01-00-5e-*` → IPv4 multicast MAC (normal)

These are static entries added by the OS and are not suspicious.

---

### Detecting ARP Spoofing

ARP spoofing (also called ARP poisoning) occurs when an attacker sends forged
ARP replies to overwrite legitimate IP-to-MAC mappings in the victims' caches.
The attacker then becomes a man-in-the-middle, intercepting all traffic.

**Indicator 1: Two IPs with the same MAC**
```
192.168.1.1    00:aa:bb:cc:dd:ee   ← Gateway — legitimate
192.168.1.50   00:aa:bb:cc:dd:ee   ← Different IP, SAME MAC — attacker
```
The attacker has mapped its MAC to both its own IP and the gateway IP.
All traffic destined for the gateway goes to the attacker instead.

**Indicator 2: Known device IP mapped to unexpected MAC**
Compare current ARP cache against a baseline taken during normal operation.
If `192.168.1.1` previously had MAC `00:50:ba:85:85:ca` and now shows
`00:aa:bb:cc:dd:ee`, the gateway ARP entry has been poisoned.

**Indicator 3: Duplicate IP conflict in Windows**
```
192.168.1.10   00-0c-29-1a-2b-3c   dynamic
192.168.1.10   00-1a-4b-c8-73-f1   dynamic   ← DUPLICATE
```
Windows may show the same IP twice with different MACs during an active
ARP spoofing attack.

**Confirming with packet capture:**
```
TOOL: capture 30
TOOL: tshark_filter gratuitous ARP from unexpected sources
```

Display filter for all ARP in tshark:
```
arp
arp.opcode == 2 and arp.src.hw_mac != <known_gateway_mac>
```

---

### Gratuitous ARP

A **gratuitous ARP** is an ARP reply sent without a corresponding request. The
sender announces its own IP-to-MAC binding to the broadcast domain.

**Legitimate uses:**
- Device boot — announces itself to update all neighbors' caches
- IP conflict detection — if someone else claims the same IP, the conflict is detected
- Failover — HSRP/VRRP virtual router failover sends gratuitous ARP to move traffic
- Interface up event — NIC driver sends gratuitous ARP when link comes up

**Suspicious gratuitous ARP:**
- High frequency (more than 1 per device per minute) — indicates active poisoning
- Source MAC does not match any known device in the inventory
- IP in the gratuitous ARP belongs to a critical device (gateway, DNS, historian)
- Appears shortly before ARP cache entries change unexpectedly

Capture gratuitous ARP:
```bash
tshark -i eth0 -Y "arp.opcode == 2 and arp.src.proto_ipv4 == arp.dst.proto_ipv4"
```

---

### Active LAN Discovery with arp-scan (Linux)

`arp-scan` is a purpose-built LAN scanner that sends ARP requests to every
possible IP in a subnet and collects the replies. It discovers hosts that do not
respond to ICMP ping (some PLCs block ping but respond to ARP).

```bash
# Scan entire subnet
arp-scan --interface=eth0 192.168.1.0/24

# Scan with OUI vendor lookup
arp-scan --localnet

# Scan specific range
arp-scan --interface=eth0 192.168.1.1-192.168.1.50
```

**Example output:**
```
192.168.1.1     00:50:ba:85:85:ca       D-Link Corporation
192.168.1.10    00:0c:29:1a:2b:3c       VMware, Inc.
192.168.1.20    00:1a:4b:c8:73:f1       Schneider Electric
192.168.1.30    00:00:54:12:34:56       Moxa Technologies Co., Ltd.
```

The vendor (OUI) column is extremely useful in ICS environments:
- Schneider Electric → likely a Modicon PLC or PowerLogic meter
- Moxa → serial-to-Ethernet gateway
- Siemens → SIMATIC PLC or SINEMA network device
- Rockwell Automation → Allen-Bradley PLC or CompactLogix

The agent uses the `arp` tool to read the OS cache (passive). For active
scanning equivalent to `arp-scan`, use `modbus_scan` for Modbus devices or
run `nmap -sn` for general host discovery (see nmap skill).

---

### Static vs Dynamic ARP Entries

| Type | Set By | Expires | Use Case |
|------|--------|---------|---------|
| Dynamic | Learned automatically via ARP protocol | Typically 2–20 minutes | Normal hosts |
| Static | Manually configured by admin | Never (until removed) | Servers, PLCs, routers |

**In ICS environments:**
PLCs, HMIs, and RTUs often have static ARP entries configured on the SCADA server.
This prevents ARP spoofing from redirecting Modbus traffic — a static entry cannot
be overwritten by a forged ARP reply.

If a device that should have a static ARP entry suddenly appears as `dynamic`,
the static entry was lost (e.g., after a reboot with no persistent config) and
the device is now vulnerable to ARP poisoning.

**Adding a static ARP entry:**
```
# Windows
arp -s 192.168.1.10 00-0c-29-1a-2b-3c

# Linux
arp -s 192.168.1.10 00:0c:29:1a:2b:3c
ip neigh add 192.168.1.10 lladdr 00:0c:29:1a:2b:3c dev eth0 nud permanent
```

---

### OUI Vendor Lookup

The first three octets of a MAC address are the Organizationally Unique Identifier
(OUI), assigned to the manufacturer. Cross-referencing OUIs identifies device types:

| OUI Prefix | Vendor | Typical ICS Device |
|-----------|--------|-------------------|
| `00:1A:4B` | Schneider Electric | Modicon, PowerLogic |
| `00:00:54` | Moxa | NPort serial gateway |
| `00:0C:29` | VMware | Virtual machine (engineering WS) |
| `00:04:9F` | Lantronix | Serial-to-Ethernet adapter |
| `00:A0:45` | Phoenix Contact | Industrial switches, PLCs |
| `00:E0:6C` | Rockwell / Allen-Bradley | PLC, CompactLogix |
| `00:1B:1B` | Siemens | SIMATIC PLC, SCALANCE switch |
| `00:30:64` | Cisco | Industrial Ethernet switches |

Unexpected OUIs (e.g., a consumer router vendor on the OT network) warrant
investigation.

---

### ICS-Specific Red Flags in ARP Data

- **PLC IP resolves to a different MAC than baseline** → Potential ARP spoofing targeting SCADA-PLC communication
- **New MAC address on the network** → Unauthorized device connected to OT LAN
- **ARP entry for historian server missing or changed** → Could indicate network disruption or attack
- **Multiple MACs for the SCADA master IP** → SCADA master being impersonated
- **Consumer or IT-vendor OUI on OT network** → Unauthorized laptop or device bridging networks

---

### Recommended Workflow: ARP Audit

```
TOOL: arp
```

1. List all IP-to-MAC mappings
2. Cross-reference each IP against the device inventory
3. Flag any IP not in the inventory
4. Check for duplicate MACs (same MAC on two IPs)
5. Verify gateway and critical server MACs against baseline
6. Check entry types — static entries on critical devices only

If anomalies found, escalate with packet capture:
```
TOOL: capture 60
TOOL: tshark_filter ARP spoofing and gratuitous ARP
TOOL: tshark_expert
```
