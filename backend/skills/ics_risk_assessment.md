---
name: ics-risk-assessment
description: >
  Perform ICS/OT cybersecurity risk assessment, audit industrial network traffic,
  evaluate SCADA security posture, and identify ICS-specific threats like TRITON,
  Industroyer, or unauthorized PLC access. Use when user asks for ICS audit,
  OT security assessment, SCADA risk, industrial cybersecurity, or ICS compliance.
license: Proprietary
metadata:
  category: industrial-security
  triggers:
    - ics audit
    - ot security
    - scada security
    - industrial security
    - ics compliance
    - ics risk
    - triton
    - industroyer
    - stuxnet
    - purdue model
    - iec 62443
    - nist csf
    - safety system
    - srp
    - sis
  tool_sequence:
    - capture
    - expert_analyze ics_audit
    - modbus_forensics
    - dnp3_forensics
    - generate_insight ics
  examples:
    - "Run an ICS security audit"
    - "Assess the OT network security posture"
    - "Check IEC 62443 compliance"
    - "Are there any ICS-specific threats in the traffic?"
    - "What's the risk level for this industrial network?"
---

## ICS Risk Assessment Workflow

### Comprehensive ICS audit
1. `capture 60` — collect industrial traffic sample (longer = more representative)
2. `expert_analyze ics_audit` — ICS-specific protocol analysis and anomaly detection
3. If Modbus present: `modbus_forensics <pcap>` for function-code breakdown
4. If DNP3 present: `dnp3_forensics <pcap>` for control command audit
5. `generate_insight ics` — structured ICS security report

### ICS threat landscape (reference when reporting)

**TRITON/TRISIS** (Schneider Electric Safety PLCs): Targets Safety Instrumented Systems (SIS). Signs: unusual traffic to SIS controllers, modified ladder logic uploads, unexpected firmware updates.

**Industroyer/CrashOverride** (Power grid): Implements IEC 61850, IEC 60870-5, DNP3, Modbus natively. Signs: multiple ICS protocol sessions from single host, abnormal DNP3 data object polling.

**Stuxnet-class**: PLC reprogramming via Step 7 project files. Signs: unusual OPC traffic, Siemens S7 protocol (TCP 102), project file transfers.

### Risk rating framework (IEC 62443 aligned)
| Finding | Zone | Recommended Rating |
|---|---|---|
| Unauthenticated control commands | Zone 0 (Safety) | CRITICAL |
| IT-OT boundary crossing | Zone 0-1 | HIGH |
| Unauthorized FC writes | Zone 1 (Control) | HIGH |
| No protocol authentication | Zone 2 (Operations) | MEDIUM |
| Cleartext protocols | Zone 3 (Enterprise) | MEDIUM |
| Outdated firmware indicators | Any | MEDIUM–HIGH |

Always recommend: network segmentation, protocol authentication, encrypted channels where possible, anomaly detection baseline.
