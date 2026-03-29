"""
Composite workflow tools: full_audit, network_recon.
Multi-step tool chains that dispatch through the unified registry.
"""
from __future__ import annotations
import json

from agent.tools.registry import register, dispatch, ToolDef


# ── Workflow definitions ─────────────────────────────────────────────────────

WORKFLOWS = {
    "full_audit": {
        "description": "capture + ICS audit + anomaly detection",
        "steps": [
            ("capture", "30"),
            ("expert_analyze", "ics_audit"),
            ("expert_analyze", "anomaly_detect"),
        ],
    },
    "network_recon": {
        "description": "ipconfig + arp + netstat combined",
        "steps": [
            ("ipconfig", "/all"),
            ("arp", ""),
            ("netstat", "-ano"),
        ],
    },
}


async def run_workflow(args: str, *, workflow_name: str) -> str:
    """Execute a multi-step workflow, collecting results from each step."""
    wf = WORKFLOWS.get(workflow_name)
    if not wf:
        return f"[workflow] Unknown workflow: '{workflow_name}'"

    results = []
    for step_name, step_args in wf["steps"]:
        step_label = f"{step_name} {step_args}".strip()
        try:
            if step_name == "capture":
                # Capture is special — returns (summary, packets)
                from agent.tools.network import run_capture
                summary, _pkts = await run_capture(step_args)
                results.append({"step": step_label, "result": summary})
            else:
                result = await dispatch(step_name, step_args)
                results.append({"step": step_label, "result": result.output})
        except Exception as e:
            results.append({"step": step_label, "error": str(e)})

    return json.dumps({"workflow": workflow_name, "steps": results}, default=str)


# ── Registration ─────────────────────────────────────────────────────────────

async def _run_full_audit(args: str) -> str:
    return await run_workflow(args, workflow_name="full_audit")


async def _run_network_recon(args: str) -> str:
    return await run_workflow(args, workflow_name="network_recon")


register(ToolDef(
    name="full_audit", category="workflow",
    description="capture + ICS audit + anomaly detection (comprehensive security assessment)",
    args_spec="", runner=_run_full_audit,
    safety="dangerous", is_workflow=True,
    keywords={"audit", "security", "ics", "comprehensive", "full"},
))

register(ToolDef(
    name="network_recon", category="workflow",
    description="ipconfig + arp + netstat combined (network reconnaissance)",
    args_spec="", runner=_run_network_recon,
    safety="safe", is_workflow=True,
    keywords={"recon", "reconnaissance", "network", "overview"},
))
