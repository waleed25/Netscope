"""Wizard definition loader — scans wizards/ directory for TOML wizard files."""
from __future__ import annotations
import logging
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from .wizard_schema import WizardDef, WizardStep

logger = logging.getLogger(__name__)


def scan_wizards(wizards_dir: Path) -> list[WizardDef]:
    """Find all .toml files in wizards_dir and parse them as wizard definitions."""
    if not wizards_dir.exists():
        return []
    defs = []
    for toml_path in sorted(wizards_dir.glob("*.toml")):
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            wizard_data = data.get("wizard", {})
            steps_raw = data.get("steps", [])
            steps = [WizardStep(**s) for s in steps_raw]
            wd = WizardDef(**wizard_data, steps=steps)
            defs.append(wd)
        except Exception as e:
            logger.warning(f"[wizard_loader] Failed to load {toml_path}: {e}")
    return defs


def get_runnable_wizards(wizards_dir: Path, installed_modules: list[str]) -> list[WizardDef]:
    """Return wizards where all required modules are installed."""
    all_wizards = scan_wizards(wizards_dir)
    return [w for w in all_wizards if all(r in installed_modules for r in w.requires)]
