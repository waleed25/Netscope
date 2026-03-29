from pydantic import BaseModel, Field


class HardwareRequires(BaseModel):
    ram_gb_min: float = 0
    gpu_modes: list[str] = ["cpu"]   # "cuda", "cpu", "api"
    needs_npcap: bool = False
    needs_libpcap: bool = False
    disk_gb_min: float = 0.5


class PythonDeps(BaseModel):
    packages: list[str] = []
    packages_gpu: list[str] = []
    process: str = "engine"   # "gateway" | "engine" | "daemon" | "worker"


class NavConfig(BaseModel):
    icon_rail: bool = False
    sidebar_section: str = ""   # "Capture" | "Tools" | "System"
    sidebar_label: str = ""
    right_panel_tab: str = ""


class SafetyConfig(BaseModel):
    max_permission: str = "read"   # "read" | "write" | "exec" | "dangerous"
    audit_log: bool = True


class ModuleManifest(BaseModel):
    name: str
    version: str = "1.0.0"
    description: str = ""
    optional: bool = True
    process: str = "engine"
    requires_modules: list[str] = []
    hardware: HardwareRequires = Field(default_factory=HardwareRequires)
    privilege: str = "user"   # "user" | "admin"
    python: PythonDeps = Field(default_factory=PythonDeps)
    provides_tools: list[str] = []
    provides_ui: list[str] = []
    provides_wizards: list[str] = []
    provides_reports: list[str] = []
    nav: NavConfig = Field(default_factory=NavConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
