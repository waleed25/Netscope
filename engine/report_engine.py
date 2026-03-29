"""Jinja2-based report generation engine.
Supports HTML and JSON output formats.
PDF requires WeasyPrint (optional — installed separately).
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_DATA_DIR = Path(__file__).parent.parent / "data" / "reports"


class ReportEngine:
    def __init__(self, templates_dir: Path | None = None, reports_dir: Path | None = None):
        self.templates_dir = templates_dir or _TEMPLATES_DIR
        self.reports_dir = reports_dir or _DATA_DIR
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=True,
        )

    def generate(self, template: str, context: dict,
                 fmt: str = "html") -> tuple[str, bytes]:
        """Generate a report. Returns (report_id, content_bytes).

        Args:
            template: template name without extension (e.g. "modbus-audit")
            context: data passed to the template
            fmt: "html", "json", or "pdf"
        """
        report_id = str(uuid.uuid4())[:8]
        timestamp = datetime.utcnow().isoformat()
        ctx = {"report_id": report_id, "generated_at": timestamp, **context}

        if fmt == "json":
            content = json.dumps(ctx, indent=2, default=str).encode()
            ext = "json"
        elif fmt == "pdf":
            html_content = self._render_html(template, ctx)
            content = self._render_pdf(html_content)
            ext = "pdf"
        else:
            content = self._render_html(template, ctx).encode()
            ext = "html"

        # Save to disk
        report_path = self.reports_dir / f"{report_id}.{ext}"
        report_path.write_bytes(content)
        logger.info(f"[report] Generated {report_id}.{ext} ({len(content)} bytes)")
        return report_id, content

    def _render_html(self, template_name: str, context: dict) -> str:
        try:
            tmpl = self._env.get_template(f"{template_name}.html.j2")
        except Exception:
            # Fallback: use base template with raw data
            tmpl = self._env.get_template("base.html.j2")
        return tmpl.render(**context)

    def _render_pdf(self, html: str) -> bytes:
        try:
            from weasyprint import HTML  # type: ignore
            return HTML(string=html).write_pdf()
        except ImportError:
            logger.warning("[report] WeasyPrint not installed — returning HTML as PDF fallback")
            return html.encode()

    def list_reports(self) -> list[dict]:
        """List all generated reports."""
        reports = []
        for p in sorted(self.reports_dir.iterdir(), reverse=True):
            if p.suffix in (".html", ".json", ".pdf"):
                stat = p.stat()
                reports.append({
                    "id": p.stem,
                    "ext": p.suffix[1:],
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                })
        return reports

    def get_report_path(self, report_id: str) -> Path | None:
        """Find report file by ID (any extension)."""
        for ext in ("html", "pdf", "json"):
            p = self.reports_dir / f"{report_id}.{ext}"
            if p.exists():
                return p
        return None
