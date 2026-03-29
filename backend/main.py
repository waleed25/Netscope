import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from api.routes import router as api_router, APP_VERSION
from api.websocket import router as ws_router
from api.modbus_routes import router as modbus_router
from api.rag_routes import router as rag_router
from api.skills_routes import router as skills_router
from api.scheduler_routes import router as scheduler_router
from channels import router as channels_router, channels_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    print(f"Wireshark Agent API starting on {settings.host}:{settings.port}")
    print(f"LLM backend: {settings.llm_backend}")

    # Eagerly open the ChromaDB collection so the first RAG query doesn't incur
    # a 60-90s cold-start delay (embedder model is still lazy-loaded on first use).
    try:
        from rag.ingest import get_collection
        await asyncio.get_event_loop().run_in_executor(None, get_collection)
        print("RAG: ChromaDB collection opened.")
    except Exception as exc:
        print(f"RAG: collection open failed at startup (non-fatal): {exc}")

    # Seed tshark documentation + skill files into RAG knowledge base.
    # Runs as a background task so startup is not blocked by network crawls.
    try:
        from rag.seed_tshark import seed_background
        asyncio.create_task(seed_background())
        print("RAG: tshark documentation seeding queued.")
    except Exception as exc:
        print(f"RAG: seed task failed to queue (non-fatal): {exc}")

    # Load Agent Skills SKILL.md definitions
    try:
        from pathlib import Path
        from agent.skill_loader import load_skills, set_skills_dir
        _skills_dir = Path(__file__).parent / "skills"
        set_skills_dir(_skills_dir)
        _loaded = load_skills(_skills_dir)
        print(f"Skills: loaded {len(_loaded)} skill definitions from {_skills_dir}.")
    except Exception as exc:
        print(f"Skills: load failed (non-fatal): {exc}")

    # Start messaging channels (Telegram / WhatsApp) from persisted config
    try:
        await channels_manager.startup()
        print("Channels: startup complete.")
    except Exception as exc:
        print(f"Channels: startup error (non-fatal): {exc}")

    # Start autonomous background scheduler
    try:
        from scheduler import get_scheduler
        get_scheduler().start()
        print("Scheduler: APScheduler started.")
    except Exception as exc:
        print(f"Scheduler: startup error (non-fatal): {exc}")

    yield

    # ── Shutdown — stop captures and Modbus sessions with per-operation timeouts ──
    from capture.live_capture import stop_capture
    from modbus.simulator import simulator_manager
    from modbus.client import client_manager

    async def _safe_stop(coro, name: str, timeout: float = 5.0):
        try:
            await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            print(f"Warning: {name} did not stop within {timeout}s, continuing shutdown.")
        except Exception as exc:
            print(f"Warning: {name} raised during shutdown: {exc}")

    await _safe_stop(stop_capture(),               "stop_capture")
    await _safe_stop(simulator_manager.stop_all(), "simulator_manager.stop_all")
    await _safe_stop(client_manager.stop_all(),    "client_manager.stop_all")
    await _safe_stop(channels_manager.shutdown(),  "channels_manager.shutdown")

    # Stop the background scheduler (non-blocking)
    try:
        from scheduler import get_scheduler
        get_scheduler().shutdown(wait=False)
        print("Scheduler: stopped.")
    except Exception as exc:
        print(f"Scheduler: shutdown error (non-fatal): {exc}")

    print("Shutdown complete.")


app = FastAPI(
    title="Wireshark AI Agent",
    description="Local LLM-powered network traffic analysis agent",
    version=APP_VERSION,
    lifespan=lifespan,
)

# Browsers send Origin: null for file:// pages (Electron renderer).
# We include "null" as a string in the origins list to allow that.
_cors_origins = list(settings.cors_origins) + ["null"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router,       prefix="/api")
app.include_router(ws_router)
app.include_router(modbus_router,    prefix="/api")
app.include_router(rag_router,       prefix="/api")
app.include_router(skills_router,    prefix="/api")
app.include_router(channels_router,  prefix="/api")
app.include_router(scheduler_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "llm_backend": settings.llm_backend}
