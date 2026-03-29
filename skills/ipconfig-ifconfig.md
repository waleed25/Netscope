---
name: ipconfig-ifconfig
version: "1.0"
description: >
  Network interface configuration inspection using ipconfig (Windows) and
  ip addr / ifconfig (Linux). Covers IPv4/IPv6 addresses, subnet masks, default
  gateways, MAC addresses, DHCP lease details, DNS configuration, multiple
  adapter detection, and cross-platform equivalents for network interface analysis.
triggers:
  - "ipconfig"
  - "ifconfig"
  - "network interface"
  - "ip address"
  - "mac address"
  - "dhcp"
  - "subnet mask"
  - "default gateway"
  - "adapter"
  - "interface config"
  - "network settings"
tools:
  - ipconfig
  - ping
parameters:
  flags:
    type: string
    required: false
    description: Additional flags such as /all (Windows) or -a (Linux)
output_format: interface table with DHCP and DNS details
---

## ipconfig / ifconfig Skill

### Running the Tool

```
TOOL: ipconfig
```

The agent runs `ipconfig /all` on Windows or `ip addr show` on Linux and returns
the complete interface configuration. Use this to inspect addresses, check DHCP
lease status, verify DNS configuration, or identify which adapters are active.

---

### Windows ipconfig Output

**Basic `ipconfig` output:**
```
Windows IP Configuration

Ethernet adapter Ethernet:
   Connection-specific DNS Suffix  . : corp.lan
   Link-local IPv6 Address . . . . . : fe80::a1b2:c3d4:e5f6:7890%5
   IPv4 Address. . . . . . . . . . . : 192.168.1.50
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 192.168.1.1
```

**Full `ipconfig /all` output adds:**
```
Ethernet adapter Ethernet:
   Description . . . . . . . . . . . : Intel(R) Ethernet Connection I219-V
   Physical Address. . . . . . . . . : 00-1A-2B-3C-4D-5E
   DHCP Enabled. . . . . . . . . . . : Yes
   Autoconfiguration Enabled . . . . : Yes
   IPv4 Address. . . . . . . . . . . : 192.168.1.50(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Lease Obtained. . . . . . . . . . : Monday, March 23, 2026 8:15:00 AM
   Lease Expires . . . . . . . . . . : Tuesday, March 24, 2026 8:15:00 AM
   Default Gateway . . . . . . . . . : 192.168.1.1
   DHCP Server . . . . . . . . . . . : 192.168.1.1
   DNS Servers . . . . . . . . . . . : 192.168.1.1
                                       8.8.8.8
   NetBIOS over Tcpip. . . . . . . . : Enabled
```

---

### Field-by-Field Reference

**IPv4 Address**
The host's IPv4 address. `(Preferred)` means this is the active address chosen
by DHCP or manual config. Multiple IPv4 addresses on one adapter are possible
(IP aliasing) and would each appear with `(Preferred)` or `(Duplicate)`.

**Subnet Mask**
Defines the network boundary. Common masks:
| Mask | CIDR | Hosts |
|------|------|-------|
| 255.255.255.0 | /24 | 254 |
| 255.255.254.0 | /23 | 510 |
| 255.255.252.0 | /22 | 1022 |
| 255.255.0.0 | /16 | 65534 |
| 255.0.0.0 | /8 | 16,777,214 |

**Default Gateway**
The router IP that handles traffic to other subnets and the internet. If missing,
the host can only communicate on its own subnet.

**Physical Address (MAC)**
The hardware identifier burned into the NIC. Format: `00-1A-2B-3C-4D-5E` (Windows
uses hyphens; Linux uses colons). The first three octets (OUI) identify the
manufacturer — useful for device identification in ICS environments.

**DHCP Enabled**
`Yes` = address assigned by a DHCP server (dynamic).
`No` = address manually configured (static). ICS devices typically use static IPs.

**Lease Obtained / Lease Expires**
How long the DHCP assignment is valid. When the lease expires, the client
re-requests from the DHCP server. If the server is unavailable, the client
enters APIPA (169.254.x.x) — which will break all communications.

**DHCP Server**
The server that issued the lease. Unexpected DHCP server IPs indicate a rogue
DHCP server on the network (man-in-the-middle risk).

**DNS Servers**
Resolves hostnames to IPs. Multiple entries are tried in order. If DNS is wrong
or unreachable, hostname-based connections fail (but IP-based connections work).

**Link-local IPv6 (fe80::)**
Auto-configured from the MAC address. Always present when IPv6 is enabled.
Does not require a DHCP server. The `%5` suffix is the interface index.

---

### Detecting Multiple Adapters

ipconfig lists every adapter, including virtual and inactive ones:

```
Ethernet adapter Ethernet:          ← Physical NIC
   IPv4 Address: 192.168.1.50

Ethernet adapter VirtualBox Host-Only:   ← VM hypervisor adapter
   IPv4 Address: 192.168.56.1

Wireless LAN adapter Wi-Fi:              ← Wireless interface
   IPv4 Address: 10.0.0.107

Tunnel adapter Teredo Tunneling:         ← IPv6 tunneling (usually disabled)
   Media State: Media disconnected
```

In ICS/OT environments, a historian or SCADA server with **both** an IT network
adapter and an OT network adapter is a bridging point — critical to secure.
If an HMI or engineering workstation has an active Wi-Fi adapter alongside
an Ethernet connection to the OT network, it is a potential wireless ingress
point that should be disabled.

---

### When to Use /all

Always use `ipconfig /all` (not just `ipconfig`) to see:
- MAC address (needed for ARP validation)
- DHCP lease times (needed for expiry troubleshooting)
- DHCP server IP (needed to detect rogue DHCP)
- DNS server IPs (needed for name resolution debugging)
- Full IPv6 addresses (needed for dual-stack environments)

The agent's `TOOL: ipconfig` automatically uses `/all`.

---

### Linux Equivalents

| Windows ipconfig | Linux equivalent | Notes |
|-----------------|-----------------|-------|
| `ipconfig` | `ip addr show` | Modern, preferred |
| `ipconfig /all` | `ip addr show` + `ip route show` | Route info is separate |
| Physical Address | `ip link show` (shows MAC in `link/ether`) | |
| Default Gateway | `ip route show default` | |
| DHCP lease info | `cat /var/lib/dhcp/dhclient.leases` | Path varies by distro |
| DNS servers | `cat /etc/resolv.conf` | |
| Flush DNS cache | `ipconfig /flushdns` → `systemd-resolve --flush-caches` | |
| Release/renew | `ipconfig /release` + `/renew` → `dhclient -r && dhclient` | |

**Linux `ip addr show` example:**
```
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq state UP
    link/ether 00:1a:2b:3c:4d:5e brd ff:ff:ff:ff:ff:ff
    inet 192.168.1.50/24 brd 192.168.1.255 scope global dynamic eth0
       valid_lft 82345sec preferred_lft 82345sec
    inet6 fe80::21a:2bff:fe3c:4d5e/64 scope link
       valid_lft forever preferred_lft forever
```

`valid_lft` is the remaining DHCP lease time in seconds.

---

### Common Troubleshooting Scenarios

**Scenario 1: Host cannot reach anything**
```
TOOL: ipconfig
```
Check:
- Is IPv4 Address in the 169.254.x.x range? → APIPA — DHCP failed
- Is Default Gateway blank? → No route out of subnet
- Is Subnet Mask correct? → Wrong mask = wrong network boundary

**Scenario 2: Can ping IP but not hostname**
```
TOOL: ipconfig
```
Check DNS Servers field:
- Is DNS server reachable? `TOOL: ping <dns_server>`
- Is it pointing to an internal DNS that may be down?

**Scenario 3: Unexpected adapter is active**
```
TOOL: ipconfig
```
Look for:
- VPN adapters showing a second IP — may cause routing loops
- Wi-Fi connected while on wired — Wi-Fi adapter may have lower metric and steal traffic
- Bridge adapters (Hyper-V, VirtualBox) intercepting traffic

**Scenario 4: IP conflict**
```
IPv4 Address. . . . . . . . . . . : 192.168.1.50 (Duplicate)
```
The word `Duplicate` means another device on the LAN is using the same IP.
Use `arp -a` to find the conflicting MAC address.

---

### ICS Relevance

In ICS environments, ipconfig is critical for:
- **Verifying static IPs** — PLCs and HMIs should have static IPs; DHCP is a red flag
- **Identifying dual-homed hosts** — a workstation bridging IT and OT networks
- **Confirming correct subnet** — OT devices on wrong subnet cannot receive SCADA polls
- **Checking DNS** — if OT devices point to internet DNS, they have internet access (security risk)
- **DHCP anomalies** — unexpected DHCP server suggests rogue device on OT network
