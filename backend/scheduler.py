"""
Autonomous background scheduler for Netscope.
Uses APScheduler AsyncIOScheduler (runs in FastAPI's event loop).
"""
from __future__ import annotations

import asyncio
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

# Singleton scheduler instance
_scheduler: AsyncIOScheduler | None = None

# In-memory job registry: job_id -> job metadata
_jobs: dict[str, dict] = {}

# Per-job run history: job_id -> deque of run records (max 20)
_history: dict[str, deque] = {}

JOB_TYPES = {"health_check", "packet_capture", "auto_insight", "anomaly_scan", "modbus_poll"}


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def _parse_schedule(schedule: str):
    """Parse schedule string to APScheduler trigger.

    Accepts:
    - Cron: '*/5 * * * *'
    - Interval: '5m', '30m', '1h', '2h', '10s'
    """
    schedule = schedule.strip()
    # Interval shorthand
    if schedule.endswith("m") and schedule[:-1].isdigit():
        return IntervalTrigger(minutes=int(schedule[:-1]))
    if schedule.endswith("h") and schedule[:-1].isdigit():
        return IntervalTrigger(hours=int(schedule[:-1]))
    if schedule.endswith("s") and schedule[:-1].isdigit():
        secs = max(10, int(schedule[:-1]))  # minimum 10s
        return IntervalTrigger(seconds=secs)
    # Cron expression (5 fields)
    parts = schedule.split()
    if len(parts) == 5:
        return CronTrigger.from_crontab(schedule)
    if len(parts) == 6:
        # 6-field cron: drop seconds field (first) and use remaining 5
        return CronTrigger.from_crontab(" ".join(parts[1:]))
    raise ValueError(f"Unrecognised schedule format: {schedule!r}")


async def _run_job(job_id: str) -> None:
    """Execute a job and record the result in history."""
    job = _jobs.get(job_id)
    if not job:
        return

    started_at = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "status": "ok",
        "output": "",
    }

    try:
        from agent.tools.registry import dispatch  # lazy import — avoids circular at module level

        job_type = job["type"]
        params = job.get("params", {})

        if job_type == "health_check":
            tool_result = await dispatch("system_status", "")
        elif job_type == "packet_capture":
            secs = params.get("seconds", 10)
            tool_result = await dispatch("capture", str(secs))
        elif job_type == "auto_insight":
            tool_result = await dispatch("generate_insight", "general")
        elif job_type == "anomaly_scan":
            tool_result = await dispatch("expert_analyze", "anomaly_detect")
        elif job_type == "modbus_poll":
            tool_result = await dispatch("list_modbus_sessions", "")
        else:
            result["status"] = "error"
            result["output"] = f"Unknown job type: {job_type}"
            tool_result = None

        if tool_result is not None:
            # dispatch() returns a ToolResult dataclass — extract .output and .status
            if hasattr(tool_result, "output"):
                raw_output = str(tool_result.output)
                raw_status = getattr(tool_result, "status", "ok")
            else:
                raw_output = str(tool_result)
                raw_status = "ok"

            result["output"] = raw_output[:2000]  # cap at 2000 chars
            if raw_status == "error":
                result["status"] = "error"

    except ImportError as exc:
        result["status"] = "error"
        result["output"] = f"[import error] Could not load tool registry: {exc}"
    except Exception as exc:
        result["status"] = "error"
        result["output"] = str(exc)[:500]

    finished_at = datetime.now(timezone.utc)
    result["finished_at"] = finished_at.isoformat()
    result["duration_ms"] = int((finished_at - started_at).total_seconds() * 1000)

    _history.setdefault(job_id, deque(maxlen=20)).appendleft(result)
    _jobs[job_id]["last_run"] = result["started_at"]
    _jobs[job_id]["last_status"] = result["status"]


def create_job(
    job_type: str,
    schedule: str,
    params: dict | None = None,
    name: str | None = None,
) -> dict:
    """Create and register a new scheduled job. Returns job metadata."""
    if job_type not in JOB_TYPES:
        raise ValueError(
            f"Invalid job type '{job_type}'. Must be one of: {sorted(JOB_TYPES)}"
        )

    trigger = _parse_schedule(schedule)
    job_id = str(uuid.uuid4())[:8]
    display_name = name or f"{job_type}-{job_id}"

    scheduler = get_scheduler()
    scheduler.add_job(
        _run_job,
        trigger=trigger,
        args=[job_id],
        id=job_id,
        name=display_name,
        replace_existing=True,
        misfire_grace_time=30,
    )

    aps_job = scheduler.get_job(job_id)
    _jobs[job_id] = {
        "id": job_id,
        "name": display_name,
        "type": job_type,
        "schedule": schedule,
        "params": params or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_run": None,
        "last_status": None,
        "next_run": (
            aps_job.next_run_time.isoformat()
            if aps_job and aps_job.next_run_time
            else None
        ),
    }
    _history[job_id] = deque(maxlen=20)
    return dict(_jobs[job_id])


def delete_job(job_id: str) -> bool:
    """Remove a job. Returns True if removed, False if not found."""
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    existed = job_id in _jobs
    _jobs.pop(job_id, None)
    _history.pop(job_id, None)
    return existed


def list_jobs() -> list[dict]:
    """Return all jobs with refreshed next_run times."""
    scheduler = get_scheduler()
    result = []
    for job_id, meta in _jobs.items():
        aps_job = scheduler.get_job(job_id)
        meta["next_run"] = (
            aps_job.next_run_time.isoformat()
            if aps_job and aps_job.next_run_time
            else None
        )
        result.append(dict(meta))
    return result


def get_job_history(job_id: str) -> list[dict]:
    """Return run history for a job (most recent first)."""
    return list(_history.get(job_id, []))


def job_exists(job_id: str) -> bool:
    """Check if a job ID exists in the registry."""
    return job_id in _jobs


async def trigger_job(job_id: str) -> None:
    """Fire a job immediately (for API use)."""
    await _run_job(job_id)
