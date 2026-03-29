"""
Meta tools: skill management (list, create, update, delete, reload).

These tools let the agent (and the user via the agent) dynamically manage
SKILL.md files without restarting the backend.
"""
from __future__ import annotations
import json

from agent.tools.registry import register, ToolDef


# ── Tool implementations ──────────────────────────────────────────────────────

async def run_list_skills(args: str = "") -> str:
    from agent.skill_loader import list_skills_info
    skills = list_skills_info()
    if not skills:
        return json.dumps({"count": 0, "skills": [], "note": "No skills loaded. Check that the skills/ directory exists."})
    return json.dumps({"count": len(skills), "skills": skills})


async def run_reload_skills(args: str = "") -> str:
    from agent.skill_loader import reload_skills
    loaded = reload_skills()
    return json.dumps({"reloaded": len(loaded), "skills": list(loaded.keys())})


async def run_get_skill(args: str = "") -> str:
    name = args.strip()
    if not name:
        return "[get_skill] Usage: get_skill <name>"
    from agent.skill_loader import get_skill_content
    ok, content = get_skill_content(name)
    if not ok:
        return f"[get_skill] {content}"
    return content


async def run_create_skill(args: str = "") -> str:
    """Create a skill from agent-provided SKILL.md content.

    Usage:  create_skill <name>
    The agent should then provide the full SKILL.md content as a follow-up.
    For programmatic creation, args can be: <name>|||<content> (pipe-delimited).
    """
    if "|||" in args:
        name, _, content = args.partition("|||")
        name = name.strip()
        content = content.strip()
    else:
        name = args.strip()
        if not name:
            return "[create_skill] Usage: create_skill <name>  (then provide SKILL.md content)"
        # Generate a minimal stub for the LLM to fill in
        content = f"""---
name: {name}
description: >
  Describe what this skill does and when to use it.
  Include trigger words that should activate this skill.
metadata:
  triggers:
    - keyword1
    - keyword2
  tool_sequence:
    - tool_name_1
    - tool_name_2
---

## Instructions

Describe the workflow here. Include:
- Step-by-step tool sequence
- How to interpret results
- Domain knowledge tables or reference
"""

    from agent.skill_loader import create_skill
    ok, msg = create_skill(name, content)
    return msg


async def run_update_skill(args: str = "") -> str:
    """Update an existing skill's content.

    Usage: update_skill <name>|||<new_content>
    """
    if "|||" not in args:
        return "[update_skill] Usage: update_skill <name>|||<new_content>"
    name, _, content = args.partition("|||")
    name = name.strip()
    content = content.strip()
    if not name or not content:
        return "[update_skill] Both name and content are required."
    from agent.skill_loader import update_skill
    ok, msg = update_skill(name, content)
    return msg


async def run_delete_skill(args: str = "") -> str:
    name = args.strip()
    if not name:
        return "[delete_skill] Usage: delete_skill <name>"
    from agent.skill_loader import delete_skill
    ok, msg = delete_skill(name)
    return msg


# ── Registration ─────────────────────────────────────────────────────────────

_META_KW = {
    "skill", "skills", "create skill", "new skill", "edit skill",
    "list skills", "delete skill", "reload skills", "add capability",
    "show skills", "manage skills", "teach", "define workflow",
}

register(ToolDef(
    name="list_skills", category="meta",
    description="list all loaded skills with triggers and tool sequences",
    args_spec="", runner=run_list_skills,
    safety="safe", keywords=_META_KW,
))

register(ToolDef(
    name="reload_skills", category="meta",
    description="re-scan skills/ directory and reload skill definitions",
    args_spec="", runner=run_reload_skills,
    safety="safe", keywords=_META_KW,
))

register(ToolDef(
    name="get_skill", category="meta",
    description="get the raw SKILL.md content for a skill by name",
    args_spec="<name>", runner=run_get_skill,
    safety="read", keywords=_META_KW,
))

register(ToolDef(
    name="create_skill", category="meta",
    description="create a new skill file (name|||content or name for a stub)",
    args_spec="<name>[|||<content>]", runner=run_create_skill,
    safety="write", keywords=_META_KW,
))

register(ToolDef(
    name="update_skill", category="meta",
    description="update an existing skill file (name|||new_content)",
    args_spec="<name>|||<content>", runner=run_update_skill,
    safety="write", keywords=_META_KW,
))

register(ToolDef(
    name="delete_skill", category="meta",
    description="delete a skill file by name",
    args_spec="<name>", runner=run_delete_skill,
    safety="dangerous", keywords=_META_KW,
))
