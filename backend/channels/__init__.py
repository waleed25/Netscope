"""
Netscope Channels — OpenClaw-inspired messaging platform connectors.
Exposes channels_manager (singleton) and router (FastAPI APIRouter).
"""
from channels.manager import channels_manager
from channels.router import router

__all__ = ["channels_manager", "router"]
