"""
REST API for Agent Skills management.

Endpoints:
  GET    /api/skills                — list all loaded skills (name, triggers, tools, …)
  GET    /api/skills/{name}         — get raw SKILL.md content for a skill
  POST   /api/skills                — create a new skill {name, content}
  PUT    /api/skills/{name}         — update an existing skill {content}
  DELETE /api/skills/{name}         — delete a skill
  POST   /api/skills/reload         — reload all skills from disk
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/skills", tags=["skills"])


# ── Request models ────────────────────────────────────────────────────────────

class CreateSkillRequest(BaseModel):
    name: str
    content: str


class UpdateSkillRequest(BaseModel):
    content: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_skills():
    """Return all loaded skills as serialisable dicts."""
    from agent.skill_loader import list_skills_info
    return list_skills_info()


@router.get("/{name}")
async def get_skill(name: str):
    """Return raw SKILL.md content for a skill."""
    from agent.skill_loader import get_skill_content
    ok, result = get_skill_content(name)
    if not ok:
        raise HTTPException(status_code=404, detail=result)
    return {"name": name, "content": result}


@router.post("")
async def create_skill(req: CreateSkillRequest):
    """Create a new skill file and reload the registry."""
    from agent.skill_loader import create_skill as _create
    ok, msg = _create(req.name, req.content)
    if not ok:
        raise HTTPException(status_code=409, detail=msg)
    return {"status": "created", "message": msg}


@router.put("/{name}")
async def update_skill(name: str, req: UpdateSkillRequest):
    """Overwrite an existing skill and reload the registry."""
    from agent.skill_loader import update_skill as _update
    ok, msg = _update(name, req.content)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    return {"status": "updated", "message": msg}


@router.delete("/{name}")
async def delete_skill(name: str):
    """Delete a skill and remove it from the registry."""
    from agent.skill_loader import delete_skill as _delete
    ok, msg = _delete(name)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    return {"status": "deleted", "message": msg}


@router.post("/reload")
async def reload_skills():
    """Re-scan the skills directory and refresh the registry."""
    from agent.skill_loader import reload_skills as _reload
    skills = _reload()
    return {"status": "reloaded", "count": len(skills)}
