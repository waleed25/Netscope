"""Wizard API endpoints."""
from __future__ import annotations
import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from shared.manifests.wizard_loader import get_runnable_wizards, scan_wizards
from shared.manifests.loader import load_installed

logger = logging.getLogger(__name__)
router = APIRouter()

_PROJECT_ROOT = Path(__file__).parent.parent
_WIZARDS_DIR = _PROJECT_ROOT / "wizards"
_DATA_DIR = _PROJECT_ROOT / "data"

# In-memory run state {run_id: {"status": ..., "steps": [...], "events": queue}}
_runs: dict[str, dict] = {}


def _get_installed_modules() -> list[str]:
    installed = load_installed(_DATA_DIR)
    if not installed:
        return []  # no installed.json = all enabled; but we can't list them
    return [name for name, info in installed.items() if info.get("enabled", True)]


@router.get("/wizards")
async def list_wizards():
    """List all runnable wizards (required modules installed)."""
    installed = _get_installed_modules()
    if not installed:
        # No installed.json — return all wizards
        wizards = scan_wizards(_WIZARDS_DIR)
    else:
        wizards = get_runnable_wizards(_WIZARDS_DIR, installed)
    return [
        {
            "name": w.name,
            "title": w.title,
            "description": w.description,
            "requires": w.requires,
            "steps": [{"id": s.id, "title": s.title, "tool": s.tool} for s in w.steps],
        }
        for w in wizards
    ]


@router.post("/wizard/run")
async def start_wizard(body: dict):
    """Start a wizard run. Returns {run_id}."""
    wizard_name = body.get("wizard")
    if not wizard_name:
        raise HTTPException(400, "wizard name required")

    all_wizards = scan_wizards(_WIZARDS_DIR)
    wdef = next((w for w in all_wizards if w.name == wizard_name), None)
    if not wdef:
        raise HTTPException(404, f"Wizard '{wizard_name}' not found")

    run_id = str(uuid.uuid4())
    q: asyncio.Queue = asyncio.Queue()
    _runs[run_id] = {"wizard": wdef, "queue": q, "status": "running", "results": {}}

    # Run wizard steps in background
    asyncio.create_task(_execute_wizard(run_id, wdef, body.get("context", {})))

    return {"run_id": run_id}


@router.get("/wizard/run/{run_id}/stream")
async def stream_wizard(run_id: str):
    """SSE stream for wizard step progress."""
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(404, "run not found")

    async def event_generator():
        q: asyncio.Queue = run["queue"]
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    if event is None:  # sentinel: done
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        break
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield "data: {\"type\": \"ping\"}\n\n"
        finally:
            _runs.pop(run_id, None)  # cleanup after stream closes

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def _execute_wizard(run_id: str, wdef, context: dict):
    """Execute wizard steps sequentially, resolving $var references."""
    run = _runs[run_id]
    q: asyncio.Queue = run["queue"]
    step_results: dict = {}

    for step in wdef.steps:
        # Check dependency
        if step.depends_on and step.depends_on not in step_results:
            await q.put({"type": "error", "step": step.id,
                          "message": f"Dependency '{step.depends_on}' not completed"})
            continue

        await q.put({"type": "step_start", "step": step.id, "title": step.title})

        try:
            # Resolve args — replace $var_name with step results
            resolved_args = _resolve_vars(step.args, step_results)
            if step.prompt:
                resolved_args["prompt"] = _resolve_str(step.prompt, step_results)

            # Import and call the tool
            from shared.manifests.tool_loader import resolve_tool_function
            fn = resolve_tool_function(step.tool)
            if fn is None:
                raise ValueError(f"Tool '{step.tool}' not available")

            if asyncio.iscoroutinefunction(fn):
                result = await fn(**resolved_args)
            else:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: fn(**resolved_args))

            step_results[step.id] = result
            run["results"][step.id] = result
            await q.put({"type": "step_done", "step": step.id, "result": str(result)[:500]})

        except Exception as e:
            logger.error(f"[wizard] Step {step.id} failed: {e}")
            await q.put({"type": "step_error", "step": step.id, "message": str(e)})

    run["status"] = "done"
    await q.put(None)  # sentinel


def _resolve_vars(args: dict, step_results: dict) -> dict:
    """Replace $step_id references in args dict with actual results."""
    resolved = {}
    for k, v in args.items():
        resolved[k] = _resolve_str(str(v), step_results) if isinstance(v, str) else v
    return resolved


def _resolve_str(s: str, step_results: dict) -> str:
    """Replace $step_id in string with step result string."""
    for step_id, result in step_results.items():
        s = s.replace(f"${step_id}", str(result)[:1000])
    return s
