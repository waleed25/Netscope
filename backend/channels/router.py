"""
FastAPI router for the Channels feature.
All endpoints are under /api/channels (prefix added in main.py).

Token values are NEVER returned in any response — always masked as "***".
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from channels.manager import channels_manager

router = APIRouter(prefix="/channels", tags=["channels"])


# ── Request schemas ───────────────────────────────────────────────────────────

class TelegramConfigRequest(BaseModel):
    token: str
    dm_policy: str = "pairing"          # "pairing" | "allowlist" | "open"
    allowed_user_ids: list[str] = Field(default_factory=list)


class WhatsAppConfigRequest(BaseModel):
    dm_policy: str = "pairing"
    allowed_user_ids: list[str] = Field(default_factory=list)
    bridge_port: int = 3500


class SendMessageRequest(BaseModel):
    user_id: str
    text: str


class PairingActionRequest(BaseModel):
    channel: str
    code: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_channels():
    """List all channels with status. Tokens are never included."""
    statuses = channels_manager.get_status()
    return [
        {
            "name": s.name,
            "connected": s.connected,
            "state": s.state,
            "error": s.error,
            "message_count": s.message_count,
        }
        for s in statuses
    ]


@router.post("/telegram/configure")
async def configure_telegram(req: TelegramConfigRequest):
    try:
        status = await channels_manager.configure_telegram(
            token=req.token,
            dm_policy=req.dm_policy,
            allowed_user_ids=req.allowed_user_ids,
        )
        return {
            "name": status.name,
            "connected": status.connected,
            "state": status.state,
            "error": status.error,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/telegram")
async def stop_telegram():
    await channels_manager.stop_channel("telegram")
    return {"status": "stopped"}


@router.post("/whatsapp/configure")
async def configure_whatsapp(req: WhatsAppConfigRequest):
    try:
        status = await channels_manager.configure_whatsapp(
            dm_policy=req.dm_policy,
            allowed_user_ids=req.allowed_user_ids,
            bridge_port=req.bridge_port,
        )
        return {
            "name": status.name,
            "connected": status.connected,
            "state": status.state,
            "error": status.error,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/whatsapp")
async def stop_whatsapp():
    await channels_manager.stop_channel("whatsapp")
    return {"status": "stopped"}


@router.get("/{name}/messages")
async def get_messages(name: str, limit: int = 50):
    if name not in ("telegram", "whatsapp"):
        raise HTTPException(status_code=404, detail="Unknown channel")
    msgs = channels_manager.get_messages(name, limit=limit)
    return {
        "channel": name,
        "messages": [
            {
                "user_id": m.user_id,
                "username": m.username,
                "text": m.text,
                "is_bot": m.is_bot,
                "timestamp": m.timestamp,
            }
            for m in msgs
        ],
    }


@router.post("/{name}/send")
async def send_message(name: str, req: SendMessageRequest):
    if name not in ("telegram", "whatsapp"):
        raise HTTPException(status_code=404, detail="Unknown channel")
    try:
        await channels_manager.send_test_message(name, req.user_id, req.text)
        return {"status": "sent"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/whatsapp/qr")
async def get_whatsapp_qr():
    qr = channels_manager.get_whatsapp_qr()
    return {"qr_b64": qr}


@router.get("/pairings")
async def get_pairings():
    """List pending (non-expired) pairing code requests across all channels."""
    return {"pairings": channels_manager.get_pending_pairings()}


@router.post("/pairings/approve")
async def approve_pairing(req: PairingActionRequest):
    entry = channels_manager.approve_pairing(req.channel, req.code)
    if entry is None:
        raise HTTPException(status_code=404, detail="Code not found or expired.")
    return {"approved": True, "user_id": entry["user_id"], "username": entry["username"]}


@router.post("/pairings/reject")
async def reject_pairing(req: PairingActionRequest):
    removed = channels_manager.reject_pairing(req.channel, req.code)
    return {"rejected": removed}
