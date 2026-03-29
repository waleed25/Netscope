"""
REST API routes for the autonomous background scheduler.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from scheduler import (
    create_job,
    delete_job,
    get_job_history,
    job_exists,
    list_jobs,
    trigger_job,
)

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


# ── Request / response models ─────────────────────────────────────────────────

class JobCreate(BaseModel):
    type: str
    schedule: str
    params: dict = Field(default_factory=dict)
    name: str | None = None


class JobTriggered(BaseModel):
    status: str
    job_id: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/jobs", summary="List all scheduled jobs")
async def get_jobs() -> list[dict]:
    """Return all registered jobs with their current next_run time."""
    return list_jobs()


@router.post("/jobs", status_code=201, summary="Create a scheduled job")
async def add_job(body: JobCreate) -> dict:
    """
    Create a new scheduled job.

    - **type**: one of `health_check`, `packet_capture`, `auto_insight`, `anomaly_scan`, `modbus_poll`
    - **schedule**: cron expression (`*/5 * * * *`) or interval shorthand (`5m`, `30m`, `1h`)
    - **params**: optional job-type-specific parameters (e.g. `{"seconds": 15}` for packet_capture)
    - **name**: optional display name
    """
    try:
        return create_job(body.type, body.schedule, body.params, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/jobs/{job_id}", status_code=204, summary="Delete a scheduled job")
async def remove_job(job_id: str) -> None:
    """Remove a job by ID. Returns 404 if not found."""
    if not delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")


@router.post(
    "/jobs/{job_id}/run",
    status_code=202,
    response_model=JobTriggered,
    summary="Trigger a job immediately",
)
async def trigger_job_endpoint(job_id: str) -> JobTriggered:
    """Fire a job immediately without waiting for its schedule."""
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    asyncio.create_task(trigger_job(job_id))
    return JobTriggered(status="triggered", job_id=job_id)


@router.get("/jobs/{job_id}/history", summary="Get job run history")
async def job_history(job_id: str) -> list[dict]:
    """Return the last 20 run records for a job (most recent first)."""
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return get_job_history(job_id)
