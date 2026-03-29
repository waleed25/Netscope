---
name: autonomous-monitor
version: "1.0"
description: >
  Autonomous network monitoring configuration: schedule recurring packet captures,
  automated insight generation, anomaly scans, and Modbus polling jobs using
  the Netscope scheduler for hands-free OT network surveillance.
triggers:
  - "autonomous"
  - "scheduled scan"
  - "auto monitor"
  - "periodic capture"
  - "watch network"
  - "cron"
  - "schedule"
  - "recurring"
  - "background monitor"
  - "automated analysis"
  - "scheduler"
tools:
  - capture
  - generate_insight
  - system_status
  - expert_analyze
parameters:
  job_type:
    type: enum
    values: [health_check, packet_capture, auto_insight, anomaly_scan, modbus_poll]
    description: "Type of scheduled monitoring job"
  schedule:
    type: string
    description: "Cron expression or interval string (e.g., '*/5 * * * *' or '5m')"
output_format: Markdown job summary + run log
---

## Autonomous Monitor Skill

### Overview

The Netscope scheduler runs monitoring jobs automatically in the background without
requiring manual intervention. Jobs can be configured to run on cron schedules or
fixed intervals, making it suitable for overnight captures, shift-change summaries,
and continuous OT network surveillance.

Jobs are managed via the **Scheduler** tab in the UI or through the REST API.

### Available Job Types

#### health_check

Runs every 5 minutes by default. Checks whether all Netscope subsystems are
operational and logs any degraded or failed components.

```
TOOL: system_status
```

Checks:
- Backend API reachability
- LLM backend connectivity and response time
- RAG ChromaDB collection health
- Packet capture interface availability
- Modbus simulator/client status

**Default schedule:** `*/5 * * * *`

#### packet_capture

Captures live traffic for a configurable duration and saves the result as a
timestamped PCAP file.

```
TOOL: capture 60
```

Parameters:
- `duration` — capture length in seconds (default: 60)
- `interface` — network interface (default: auto-detected)
- `output_dir` — where to save PCAP files (default: `captures/`)

**Example schedule:** `0 * * * *` — capture 60 seconds at the top of every hour.

PCAP files are named `capture_YYYYMMDD_HHMMSS.pcap` and stored locally.
They can be loaded into the Packets tab for analysis at any time.

#### auto_insight

Generates an insight from the most recently captured packets. Combines
`generate_insight general` with `generate_insight ics_protocols` into a
single summary report.

```
TOOL: generate_insight general
TOOL: generate_insight ics_protocols
```

**Default schedule:** `*/30 * * * *` — every 30 minutes.

Output is written to the Insights store and visible in the Insights tab.
Each run appends a timestamped entry — history is preserved across runs.

#### anomaly_scan

Runs statistical anomaly detection on recent packets and logs any findings
with timestamps. Designed to surface unexpected behavior automatically.

```
TOOL: expert_analyze anomaly_detect
```

Logged findings include:
- New hosts not seen in the previous run
- Protocol violations
- Unusual packet sizes
- Traffic at unexpected times

**Default schedule:** `*/10 * * * *` — every 10 minutes.

All findings are logged with severity (INFO / WARNING / CRITICAL) and
are viewable in the Scheduler tab → job history.

#### modbus_poll

Periodically polls all active Modbus sessions and logs register values.
Useful for trend analysis and detecting unauthorized register changes.

Parameters:
- `session_ids` — list of Modbus session IDs to poll (or `all`)
- `registers` — register address range (e.g., `0-100`)

**Example schedule:** `*/1 * * * *` — poll every minute.

Register values are stored as time series. Deviations from a rolling
baseline trigger a WARNING log entry.

### Schedule Syntax

Jobs accept either cron expressions or shorthand intervals:

| Format | Example | Meaning |
|--------|---------|---------|
| Cron | `*/5 * * * *` | Every 5 minutes |
| Cron | `0 9 * * 1-5` | Weekdays at 9:00 AM |
| Cron | `0 0 * * *` | Daily at midnight |
| Cron | `0 */4 * * *` | Every 4 hours |
| Interval | `5m` | Every 5 minutes |
| Interval | `30m` | Every 30 minutes |
| Interval | `1h` | Every hour |

### Configuring Jobs via the UI

1. Open the **Scheduler** tab
2. Click **Add Job**
3. Select job type from the dropdown
4. Enter the schedule (cron or interval)
5. Configure job-specific parameters
6. Click **Create Job**

Jobs start running immediately on the next schedule trigger.

### Configuring Jobs via API

```
POST /scheduler/jobs
{
  "type": "anomaly_scan",
  "schedule": "*/10 * * * *",
  "params": {}
}

POST /scheduler/jobs
{
  "type": "packet_capture",
  "schedule": "0 * * * *",
  "params": {
    "duration": 60,
    "interface": "eth0"
  }
}
```

### Viewing Job History

1. Open the **Scheduler** tab
2. Click on any job to expand it
3. The last 20 run results are shown with timestamps, duration, and status
4. Anomaly findings and insight text are included inline

### Recommended Configurations

**Continuous OT network monitoring:**
```
health_check    — */5 * * * *     (every 5 min)
packet_capture  — */15 * * * *    (every 15 min, 30 s capture)
anomaly_scan    — */10 * * * *    (every 10 min)
modbus_poll     — */1 * * * *     (every minute)
```

**Overnight unattended capture:**
```
packet_capture  — 0 22 * * *     (start at 10 PM, 8-hour duration)
auto_insight    — 0 6 * * *      (summarize at 6 AM)
```

**Shift-change summary:**
```
auto_insight    — 0 6,14,22 * * *   (generate at each shift start)
```

### Alert Behavior

- `anomaly_scan` CRITICAL findings generate a desktop notification (if enabled)
- WARNING and INFO findings are written to the job log only
- All findings include a timestamp and the raw packet evidence that triggered them
- No automatic remediation actions are taken — monitoring only
