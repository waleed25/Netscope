"""Report API endpoints — proxy to engine report_engine."""
from __future__ import annotations
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_PROJECT_ROOT = Path(__file__).parent.parent
_REPORTS_DIR = _PROJECT_ROOT / "data" / "reports"


@router.post("/report/generate")
async def generate_report(body: dict):
    """Generate a report. Body: {template, data, format}."""
    template = body.get("template", "base")
    data = body.get("data", {})
    fmt = body.get("format", "html")

    try:
        # Import engine report engine (may need to run via Redis in full multi-process setup)
        # For now, gateway calls it directly (engine code is on same Python path)
        from engine.report_engine import ReportEngine
        engine = ReportEngine()
        report_id, _ = engine.generate(template, data, fmt)
        return {"report_id": report_id, "format": fmt}
    except Exception as e:
        logger.error(f"[report] Generation failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/reports")
async def list_reports():
    """List all generated reports."""
    try:
        from engine.report_engine import ReportEngine
        engine = ReportEngine()
        return engine.list_reports()
    except Exception as e:
        logger.error(f"[report] List failed: {e}")
        return []


@router.get("/report/{report_id}")
async def get_report(report_id: str):
    """Return the report file (HTML, PDF, or JSON)."""
    # Sanitize report_id: only alphanumeric and hyphens
    import re
    if not re.match(r'^[a-f0-9\-]+$', report_id):
        raise HTTPException(400, "Invalid report ID")

    try:
        from engine.report_engine import ReportEngine
        engine = ReportEngine()
        path = engine.get_report_path(report_id)
        if not path:
            raise HTTPException(404, "Report not found")

        media_types = {"html": "text/html", "pdf": "application/pdf", "json": "application/json"}
        media_type = media_types.get(path.suffix[1:], "application/octet-stream")
        return FileResponse(str(path), media_type=media_type)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
