import json
from pathlib import Path

try:
    import tomllib           # Python 3.11+
except ImportError:
    import tomli as tomllib  # fallback

from .schema import ModuleManifest


def scan_modules(modules_dir: Path) -> list[ModuleManifest]:
    """Find all manifest.toml files under modules_dir and parse them."""
    manifests = []
    for toml_path in sorted(modules_dir.glob("*/manifest.toml")):
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            # Flatten nested TOML structure into flat dict for Pydantic
            flat = _flatten_manifest(data)
            manifests.append(ModuleManifest(**flat))
        except Exception as e:
            print(f"[manifests] Warning: failed to load {toml_path}: {e}")
    return manifests


def load_installed(data_dir: Path) -> dict:
    """Read data/installed.json. Returns {name: {enabled, version}}."""
    p = data_dir / "installed.json"
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            data = json.load(f)
        return data.get("modules", {})
    except Exception:
        return {}


def get_enabled_manifests(modules_dir: Path, data_dir: Path) -> list[ModuleManifest]:
    """Return manifests for modules that are enabled in installed.json.
    If installed.json is absent, all modules are considered enabled."""
    all_manifests = scan_modules(modules_dir)
    installed = load_installed(data_dir)
    if not installed:
        return all_manifests   # first run: enable everything
    return [m for m in all_manifests if installed.get(m.name, {}).get("enabled", True)]


def _flatten_manifest(data: dict) -> dict:
    """Convert nested TOML dict to flat dict matching ModuleManifest fields."""
    flat: dict = {}
    module = data.get("module", {})
    flat.update({k: v for k, v in module.items()})

    requires = data.get("requires", {})
    if "hardware" in requires:
        flat["hardware"] = requires["hardware"]
    if "privilege" in requires:
        flat["privilege"] = requires["privilege"]

    if "python" in data:
        flat["python"] = data["python"]

    provides = data.get("provides", {})
    flat["provides_tools"] = provides.get("tools", [])
    flat["provides_ui"] = provides.get("ui", [])
    flat["provides_wizards"] = provides.get("wizards", [])
    flat["provides_reports"] = provides.get("reports", [])

    if "nav" in provides:
        flat["nav"] = provides["nav"]

    if "safety" in data:
        flat["safety"] = data["safety"]

    return flat
