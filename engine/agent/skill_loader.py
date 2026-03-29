"""
Dynamic SKILL.md loader — reads Agent Skills-compatible SKILL.md files from
``skills/*.md`` and injects matched skill context into the LLM system prompt.

Follows the Agent Skills open standard (agentskills.io, Dec 2025) with Netscope
extensions in the ``metadata`` frontmatter block.

Three-level progressive disclosure:
  L1 — build_skill_list()    : name + description only (~20 tokens/skill, always)
  L2 — build_skill_context() : full body injected when skill matched
  L3 — references/           : external files, loaded on demand (future)

Skills are advisory: they enrich the system prompt with orchestration
context (which tools to use, parameter hints, output format expectations)
but do NOT register new tools.  The ``ToolDef`` registry remains the
single source of truth for executable capabilities.
"""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Skills directory — set by main.py at startup
_SKILLS_DIR: Path | None = None

# ── Data model ───────────────────────────────────────────────────────────────


@dataclass
class SkillDef:
    name: str
    version: str
    description: str
    triggers: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    output_format: str = ""
    body: str = ""  # markdown instruction body (below frontmatter)


# ── Registry ─────────────────────────────────────────────────────────────────

SKILL_REGISTRY: dict[str, SkillDef] = {}


def load_skills(skills_dir: Path) -> dict[str, SkillDef]:
    """Parse all ``*.md`` files in *skills_dir* and populate SKILL_REGISTRY.

    Each file must have YAML frontmatter delimited by ``---`` lines.
    Uses a lightweight regex parser (no PyYAML dependency required).
    """
    SKILL_REGISTRY.clear()

    if not skills_dir.is_dir():
        log.warning("Skills directory not found: %s", skills_dir)
        return SKILL_REGISTRY

    for md_file in sorted(skills_dir.glob("*.md")):
        try:
            skill = _parse_skill_file(md_file)
            if skill:
                SKILL_REGISTRY[skill.name] = skill
        except Exception as exc:
            log.warning("Failed to parse skill %s: %s", md_file.name, exc)

    log.info("Skills: loaded %d skill definitions from %s", len(SKILL_REGISTRY), skills_dir)
    return SKILL_REGISTRY


# ── Matching ─────────────────────────────────────────────────────────────────

def match_skills(question: str, top_n: int = 2) -> list[SkillDef]:
    """Return up to *top_n* skills whose triggers match *question*.

    Scoring: each trigger phrase that appears (case-insensitive) in the
    question adds 1 point.  Skills with score 0 are excluded.
    """
    q_lower = question.lower()
    scored: list[tuple[int, SkillDef]] = []

    for skill in SKILL_REGISTRY.values():
        score = sum(1 for t in skill.triggers if t.lower() in q_lower)
        if score > 0:
            scored.append((score, skill))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:top_n]]


def skill_matches_strongly(question: str) -> bool:
    """Return True when a skill matches with >=2 trigger hits.

    Used by vague-query detection to avoid unnecessary clarification
    prompts when the user's intent maps to a known skill.
    """
    q_lower = question.lower()
    for skill in SKILL_REGISTRY.values():
        score = sum(1 for t in skill.triggers if t.lower() in q_lower)
        if score >= 2:
            return True
    return False


# ── Context builder ──────────────────────────────────────────────────────────

def build_skill_context(skills: list[SkillDef]) -> str:
    """Build a prompt block from matched skills.

    Each skill block includes:
    - Name + one-line description
    - Recommended tools (from skill.tools)
    - Parameter hints (required params only)
    - Output format expectation

    Kept concise (~200-300 tokens per skill) to avoid prompt bloat.
    """
    if not skills:
        return ""

    blocks: list[str] = []
    for skill in skills:
        lines = [
            f"[Skill: {skill.name}] {skill.description.strip()}",
        ]
        if skill.tools:
            lines.append(f"  Recommended tools: {', '.join(skill.tools)}")
        if skill.parameters:
            param_hints = []
            for pname, pdef in skill.parameters.items():
                if isinstance(pdef, dict):
                    desc = pdef.get("description", "")
                    required = pdef.get("required", False)
                    if required:
                        param_hints.append(f"{pname} (required): {desc}")
                    else:
                        param_hints.append(f"{pname}: {desc}")
            if param_hints:
                lines.append("  Parameters: " + "; ".join(param_hints))
        if skill.output_format:
            lines.append(f"  Output format: {skill.output_format}")
        blocks.append("\n".join(lines))

    header = "Matched skills for this query (use their recommended tools):\n"
    return header + "\n\n".join(blocks)


# ── Frontmatter parser ───────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_skill_file(path: Path) -> SkillDef | None:
    """Parse a SKILL.md file with YAML-like frontmatter.

    Uses simple line-by-line parsing instead of a full YAML library
    to avoid the dependency.  Handles the fields we care about:
    name, version, description, triggers (list), tools (list),
    parameters (nested dict), output_format.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None

    fm_text = m.group(1)
    body = text[m.end():]

    fm = _parse_simple_yaml(fm_text)
    if not fm.get("name"):
        return None

    # Support both top-level triggers/tools and metadata.triggers/tool_sequence
    metadata = fm.get("metadata", {}) if isinstance(fm.get("metadata"), dict) else {}
    triggers = (
        _ensure_list(fm.get("triggers", []))
        or _ensure_list(metadata.get("triggers", []))
    )
    tools = (
        _ensure_list(fm.get("tools", []))
        or _ensure_list(metadata.get("tool_sequence", []))
    )

    return SkillDef(
        name=fm.get("name", path.stem),
        version=str(fm.get("version", "1.0")),
        description=fm.get("description", ""),
        triggers=triggers,
        tools=tools,
        parameters=fm.get("parameters", {}),
        output_format=fm.get("output_format", ""),
        body=body.strip(),
    )


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Minimal YAML-subset parser for skill frontmatter.

    Handles:
    - ``key: value`` (scalar)
    - ``key: >\\n  multi-line`` (folded string)
    - ``key:\\n  - item`` (list)
    - ``key:\\n  subkey:\\n    subsubkey: value`` (nested dict, 2 levels)
    """
    result: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip blank lines and comments
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Top-level key detection
        colon_idx = stripped.find(":")
        if colon_idx < 0:
            i += 1
            continue

        key = stripped[:colon_idx].strip()
        rest = stripped[colon_idx + 1:].strip()

        if rest == ">" or rest == "|":
            # Folded/literal block scalar — collect indented continuation
            i += 1
            parts = []
            while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                parts.append(lines[i].strip())
                i += 1
            result[key] = " ".join(p for p in parts if p)
            continue

        if rest == "" or rest is None:
            # Could be a list or nested dict — peek at next lines
            i += 1
            items: list[str] = []
            nested: dict[str, Any] = {}
            while i < len(lines) and (lines[i].startswith("  ") or lines[i].startswith("\t")):
                sub = lines[i].strip()
                if sub.startswith("- "):
                    # List item
                    items.append(sub[2:].strip().strip('"').strip("'"))
                elif ":" in sub:
                    # Nested key-value
                    sk, sv = sub.split(":", 1)
                    sk = sk.strip()
                    sv = sv.strip()
                    if sv == "" or sv is None:
                        # Sub-nested dict or list (e.g. metadata.triggers: [- item])
                        i += 1
                        subdict: dict[str, Any] = {}
                        sub_items: list[str] = []
                        while i < len(lines) and lines[i].startswith("    "):
                            ssline = lines[i].strip()
                            if ssline.startswith("- "):
                                sub_items.append(ssline[2:].strip().strip('"').strip("'"))
                            elif ":" in ssline:
                                ssk, ssv = ssline.split(":", 1)
                                subdict[ssk.strip()] = _parse_scalar(ssv.strip())
                            i += 1
                        nested[sk] = sub_items if sub_items else subdict
                        continue
                    else:
                        nested[sk] = _parse_scalar(sv)
                i += 1

            if items:
                result[key] = items
            elif nested:
                result[key] = nested
            else:
                result[key] = ""
            continue

        # Simple key: value
        result[key] = _parse_scalar(rest)
        i += 1

    return result


def _parse_scalar(val: str) -> Any:
    """Parse a YAML scalar value."""
    val = val.strip().strip('"').strip("'")
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _ensure_list(val: Any) -> list[str]:
    """Ensure a value is a list of strings."""
    if isinstance(val, list):
        return [str(x) for x in val]
    if isinstance(val, str) and val:
        return [val]
    return []


# ── L1: compact skill list (always injected) ─────────────────────────────────

def build_skill_list() -> str:
    """
    L1 prompt injection: name + description for every loaded skill (~20 tokens/skill).

    This compact awareness layer tells the LLM what skills exist without
    loading full bodies. Aligned with Agent Skills progressive disclosure.
    """
    if not SKILL_REGISTRY:
        return ""
    lines = ["Available skills (provide expert guidance when triggered):"]
    for skill in sorted(SKILL_REGISTRY.values(), key=lambda s: s.name):
        desc = skill.description.strip().replace("\n", " ")[:120]
        lines.append(f"  [{skill.name}] {desc}")
    return "\n".join(lines)


# ── Skill management (CRUD) ───────────────────────────────────────────────────

def get_skills_dir() -> Path | None:
    """Return the current skills directory, or None if not configured."""
    return _SKILLS_DIR


def set_skills_dir(path: Path) -> None:
    """Set the skills directory (called by main.py at startup)."""
    global _SKILLS_DIR
    _SKILLS_DIR = path


def reload_skills() -> dict[str, SkillDef]:
    """Re-scan the skills directory and refresh SKILL_REGISTRY in place."""
    if _SKILLS_DIR is None:
        log.warning("Skills directory not configured; cannot reload.")
        return SKILL_REGISTRY
    return load_skills(_SKILLS_DIR)


def list_skills_info() -> list[dict]:
    """Return all skills as serialisable dicts (for API responses)."""
    return [
        {
            "name": s.name,
            "version": s.version,
            "description": s.description,
            "triggers": s.triggers,
            "tools": s.tools,
            "output_format": s.output_format,
            "body_length": len(s.body),
        }
        for s in sorted(SKILL_REGISTRY.values(), key=lambda x: x.name)
    ]


def _sanitize_skill_name(name: str) -> str:
    """Sanitize a skill name to a safe filename (kebab-case, no path chars)."""
    import re as _re
    name = name.strip().lower()
    name = _re.sub(r"[^a-z0-9\-]", "-", name)
    name = _re.sub(r"-+", "-", name).strip("-")
    return name[:64] or "unnamed"


def create_skill(name: str, content: str) -> tuple[bool, str]:
    """
    Write a new skill file to the skills directory.

    Returns (success, message). The skills registry is reloaded on success.
    """
    if _SKILLS_DIR is None:
        return False, "Skills directory not configured."

    safe_name = _sanitize_skill_name(name)
    skill_path = _SKILLS_DIR / f"{safe_name}.md"

    if skill_path.exists():
        return False, f"Skill '{safe_name}' already exists. Use update_skill to modify it."

    try:
        _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(content, encoding="utf-8")
        reload_skills()
        return True, f"Skill '{safe_name}' created and loaded."
    except Exception as exc:
        return False, f"Failed to create skill: {exc}"


def update_skill(name: str, content: str) -> tuple[bool, str]:
    """
    Overwrite an existing skill file and reload the registry.
    """
    if _SKILLS_DIR is None:
        return False, "Skills directory not configured."

    safe_name = _sanitize_skill_name(name)
    skill_path = _SKILLS_DIR / f"{safe_name}.md"

    if not skill_path.exists():
        return False, f"Skill '{safe_name}' not found. Use create_skill to add it."

    try:
        skill_path.write_text(content, encoding="utf-8")
        reload_skills()
        return True, f"Skill '{safe_name}' updated and reloaded."
    except Exception as exc:
        return False, f"Failed to update skill: {exc}"


def delete_skill(name: str) -> tuple[bool, str]:
    """
    Delete a skill file and remove it from the registry.
    """
    if _SKILLS_DIR is None:
        return False, "Skills directory not configured."

    safe_name = _sanitize_skill_name(name)
    skill_path = _SKILLS_DIR / f"{safe_name}.md"

    if not skill_path.exists():
        return False, f"Skill '{safe_name}' not found."

    try:
        skill_path.unlink()
        SKILL_REGISTRY.pop(safe_name, None)
        # Try exact match and name-normalized match
        to_remove = [k for k, v in SKILL_REGISTRY.items()
                     if v.name == name or v.name == safe_name]
        for k in to_remove:
            del SKILL_REGISTRY[k]
        return True, f"Skill '{safe_name}' deleted."
    except Exception as exc:
        return False, f"Failed to delete skill: {exc}"


def get_skill_content(name: str) -> tuple[bool, str]:
    """Return the raw file content of a skill (for editing)."""
    if _SKILLS_DIR is None:
        return False, "Skills directory not configured."

    safe_name = _sanitize_skill_name(name)
    skill_path = _SKILLS_DIR / f"{safe_name}.md"

    if not skill_path.exists():
        return False, f"Skill '{safe_name}' not found."

    try:
        return True, skill_path.read_text(encoding="utf-8")
    except Exception as exc:
        return False, f"Failed to read skill: {exc}"
