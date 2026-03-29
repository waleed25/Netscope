"""
Background autonomous task runner.

Allows submitting agent goals that run in the background with progress tracking.
Uses the same building blocks as chat.py but records each tool call for progress.
"""
from __future__ import annotations
import asyncio
import time
import uuid
import logging
from collections import OrderedDict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AgentTask:
    task_id: str
    goal: str
    status: str = "running"  # "running" | "done" | "error"
    progress: list[dict] = field(default_factory=list)
    final_answer: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None


_tasks: OrderedDict[str, AgentTask] = OrderedDict()
_MAX_TASKS = 20


def create_task(goal: str) -> AgentTask:
    """Create a new task entry and return it."""
    task_id = str(uuid.uuid4())[:8]
    task = AgentTask(task_id=task_id, goal=goal)
    _tasks[task_id] = task
    # Evict oldest if over limit
    while len(_tasks) > _MAX_TASKS:
        _tasks.popitem(last=False)
    return task


def get_task(task_id: str) -> AgentTask | None:
    return _tasks.get(task_id)


def list_tasks() -> list[dict]:
    return [
        {
            "task_id": t.task_id,
            "goal": t.goal,
            "status": t.status,
            "tool_calls": len(t.progress),
            "created_at": t.created_at,
            "finished_at": t.finished_at,
        }
        for t in reversed(_tasks.values())
    ]


async def run_task(task_id: str, goal: str, max_rounds: int = 20) -> None:
    """Run the agent loop in the background, recording progress."""
    from agent.llm_client import chat_completion
    from agent.chat import _base_messages, _find_tool_call, _strip_tool_lines, _PERSONA_PROMPT
    from agent.tools import dispatch, build_prompt
    from config import settings

    task = _tasks.get(task_id)
    if not task:
        return

    try:
        # Build initial messages with autonomous prompt
        packets: list[dict] = []
        messages, _ = await _base_messages(packets, None, goal, False, False)

        # Add autonomous instruction
        sys_content = messages[0]["content"]
        sys_content += (
            "\n\n[AUTONOMOUS BACKGROUND TASK]\n"
            "You are running as a background task. Chain multiple tools to "
            "achieve the goal. Report complete findings when done.\n"
            f"Goal: {goal}\n"
            f"Max rounds: {max_rounds}"
        )
        messages[0]["content"] = sys_content
        messages.append({"role": "user", "content": goal})

        response = ""
        for _round in range(max_rounds + 1):
            response = await chat_completion(messages, max_tokens=settings.llm_max_tokens)

            tool_call = _find_tool_call(response)
            if not tool_call:
                break

            name, args = tool_call
            result = await dispatch(name, args, allow_dangerous=True)

            # Record progress
            task.progress.append({
                "round": _round + 1,
                "tool": name,
                "args": args,
                "status": result.status,
                "output": result.output[:500],  # Truncate for storage
                "duration_ms": round(result.duration_ms, 1),
                "timestamp": time.time(),
            })

            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": f"TOOL_RESULT for `{name} {args}`:\n```\n{result.output}\n```\nContinue working toward the goal.",
            })

        task.final_answer = _strip_tool_lines(response)
        task.status = "done"

    except Exception as e:
        logger.exception("Background task %s failed", task_id)
        task.status = "error"
        task.final_answer = f"Task failed: {e}"

    finally:
        task.finished_at = time.time()
