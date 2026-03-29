"""TOML-based wizard definition schema."""
from pydantic import BaseModel, Field


class WizardStepArg(BaseModel):
    """Value or $variable reference for a step argument."""
    pass  # steps pass args as dict[str, Any]


class WizardStep(BaseModel):
    id: str
    title: str = ""
    tool: str
    args: dict = Field(default_factory=dict)
    prompt: str = ""            # for llm_analyze/llm_chat tools
    template: str = ""          # for report_generate tool
    depends_on: str = ""        # step id this depends on


class WizardDef(BaseModel):
    name: str
    title: str = ""
    description: str = ""
    requires: list[str] = []    # module names that must be installed
    steps: list[WizardStep] = []
