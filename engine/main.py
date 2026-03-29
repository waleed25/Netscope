"""
NetScope AI Engine — headless GPU process.

Subscribes to chat/insight/expert/RAG Redis streams, executes
LLM-based operations, and publishes results back.

This process owns:
  - The agent chat loop (tool-calling, multi-turn)
  - RAG pipeline (ChromaDB, embeddings, reranking)
  - Expert analysis functions
  - All 17 agent tools
  - Skill loader

Communication:
  - Subscribes to: chat.request, insight.request, expert.request, rag.request, state.response
  - Publishes to:  chat.response, insight.response, expert.response, rag.response
  - RPC to Daemon: tool.request → tool.response (for capture/modbus tools)
  - RPC to Gateway: state.request → state.response (for packets/insights)
  - Health:        ns:health.engine (heartbeat)
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import time
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_ENGINE_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _ENGINE_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))         # for `shared.*`
sys.path.insert(0, str(_ENGINE_DIR))            # for `agent.*`, `rag.*`, etc.

from shared.bus import RedisBus
from shared import events

logging.basicConfig(
    level=logging.INFO,
    format="[engine] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("engine")

bus = RedisBus(process_name="engine")


# ── State proxy setup ────────────────────────────────────────────────────────
# Lazy import — initialized after bus.connect()

_state_proxy = None


def _init_state_proxy():
    """Wire up the state proxy so agent tools can fetch packets from Gateway."""
    global _state_proxy
    from engine.state_proxy import set_bus
    set_bus(bus)


# ── Chat handler ─────────────────────────────────────────────────────────────

async def handle_chat():
    """Listen for chat.request messages and run the agent loop."""
    logger.info("Listening on %s", events.CHAT_REQUEST)

    async for msg_id, data in bus.subscribe(events.CHAT_REQUEST, last_id="$"):
        correlation_id = data.get("_correlation_id", "")
        reply_to = data.get("_reply_to", events.CHAT_RESPONSE)
        message = data.get("message", "")
        stream = data.get("stream", False)

        try:
            from agent import chat as chat_agent

            if stream:
                # Stream tokens back one at a time
                async for token_data in chat_agent.answer_question_stream(
                    message,
                    packets=[],  # TODO: fetch from Gateway via state_proxy
                    insights=[],
                ):
                    await bus.publish(reply_to, {
                        "_correlation_id": correlation_id,
                        "token": token_data.get("token", ""),
                        "sentinel": token_data.get("sentinel", ""),
                        "done": False,
                    })
                # Final done marker
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "token": "",
                    "done": True,
                })
            else:
                # Non-streaming: collect full response
                response = await chat_agent.answer_question(message, [], [])
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "response": response,
                    "done": True,
                })

        except Exception as exc:
            logger.error("chat.request error: %s", exc)
            await bus.publish(reply_to, {
                "_correlation_id": correlation_id,
                "error": str(exc),
                "done": True,
            })


# ── Insight handler ──────────────────────────────────────────────────────────

async def handle_insights():
    """Listen for insight.request and generate insights using the analyzer."""
    logger.info("Listening on %s", events.INSIGHT_REQUEST)

    async for msg_id, data in bus.subscribe(events.INSIGHT_REQUEST, last_id="$"):
        correlation_id = data.get("_correlation_id", "")
        reply_to = data.get("_reply_to", events.INSIGHT_RESPONSE)
        mode = data.get("mode", "general")

        try:
            from agent import analyzer
            from engine.state_proxy import get_packets

            packets = await get_packets(limit=5000)
            if not packets:
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "insight": "[generate_insight] No packets available.",
                    "mode": mode,
                    "done": True,
                })
                continue

            result = await analyzer.generate_insights(packets, mode=mode)
            await bus.publish(reply_to, {
                "_correlation_id": correlation_id,
                "insight": result,
                "mode": mode,
                "done": True,
            })

        except Exception as exc:
            logger.error("insight.request error: %s", exc)
            await bus.publish(reply_to, {
                "_correlation_id": correlation_id,
                "error": str(exc),
                "done": True,
            })


# ── Expert analysis handler ──────────────────────────────────────────────────

async def handle_expert():
    """Listen for expert.request and run expert analysis functions."""
    logger.info("Listening on %s", events.EXPERT_REQUEST)

    async for msg_id, data in bus.subscribe(events.EXPERT_REQUEST, last_id="$"):
        correlation_id = data.get("_correlation_id", "")
        reply_to = data.get("_reply_to", events.EXPERT_RESPONSE)
        action = data.get("action", "")
        mode = data.get("mode", "")

        try:
            from agent import expert as expert_agent
            from engine.state_proxy import get_packets

            if action == events.ExpertAction.ANALYZE:
                packets = await get_packets(limit=5000)
                if not packets:
                    await bus.publish(reply_to, {
                        "_correlation_id": correlation_id,
                        "error": "No packets available",
                        "done": True,
                    })
                    continue

                modes = {
                    "ics_audit": expert_agent.ics_audit,
                    "port_scan": expert_agent.port_scan_detection,
                    "flow_analysis": expert_agent.flow_analysis,
                    "conversations": expert_agent.conversations,
                    "anomaly_detect": expert_agent.anomaly_detect,
                }
                fn = modes.get(mode)
                if not fn:
                    await bus.publish(reply_to, {
                        "_correlation_id": correlation_id,
                        "error": f"Unknown mode '{mode}'. Valid: {list(modes)}",
                        "done": True,
                    })
                    continue

                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, fn, packets)
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "result": result,
                    "mode": mode,
                    "done": True,
                })

            else:
                await bus.publish(reply_to, {
                    "_correlation_id": correlation_id,
                    "error": f"Unknown expert action: {action}",
                    "done": True,
                })

        except Exception as exc:
            logger.error("expert.request error: %s", exc)
            await bus.publish(reply_to, {
                "_correlation_id": correlation_id,
                "error": str(exc),
                "done": True,
            })


# ── RAG handler ──────────────────────────────────────────────────────────────

async def handle_rag():
    """Listen for rag.request and handle RAG operations."""
    logger.info("Listening on %s", events.RAG_REQUEST)

    async for msg_id, data in bus.subscribe(events.RAG_REQUEST, last_id="$"):
        correlation_id = data.get("_correlation_id", "")
        reply_to = data.get("_reply_to", events.RAG_RESPONSE)
        action = data.get("action", "")

        try:
            result = await _dispatch_rag(action, data)
            await bus.publish(reply_to, {
                "_correlation_id": correlation_id,
                **result,
            })
        except Exception as exc:
            logger.error("rag.request error (%s): %s", action, exc)
            await bus.publish(reply_to, {
                "_correlation_id": correlation_id,
                "error": str(exc),
            })


async def _dispatch_rag(action: str, data: dict) -> dict:
    """Route a RAG action to the appropriate function."""
    if action == events.RAGAction.QUERY:
        from rag.retriever import retrieve
        query = data.get("query", "")
        n_results = data.get("n_results", 5)
        use_hyde = data.get("use_hyde", False)
        chunks = await retrieve(query, n_results=n_results, use_hyde=use_hyde)
        context = "\n\n---\n\n".join(c.get("text", "") for c in chunks)
        return {"context": context, "chunks": chunks, "count": len(chunks)}

    elif action == events.RAGAction.STATUS:
        from rag.ingest import get_collection
        loop = asyncio.get_running_loop()
        coll = await loop.run_in_executor(None, get_collection)
        count = coll.count() if coll else 0
        return {"status": "ok", "document_count": count}

    elif action == events.RAGAction.LIST_SOURCES:
        from rag.ingest import list_sources
        sources = list_sources()
        return {"sources": sources, "count": len(sources)}

    else:
        return {"error": f"Unknown RAG action: {action}"}


# ── Main entry point ─────────────────────────────────────────────────────────

async def main():
    """Start the engine and run all handlers concurrently."""
    logger.info("NetScope AI Engine starting...")
    await bus.connect(retry=True, max_retries=60, delay=1.0)
    logger.info("Connected to Redis")

    # Initialize state proxy for tools to fetch packets from Gateway
    _init_state_proxy()

    # Load skills (non-blocking)
    try:
        from agent.skill_loader import load_skills
        skills_dir = _ENGINE_DIR / "skills"
        if skills_dir.exists():
            load_skills(skills_dir)
            logger.info("Skills loaded from %s", skills_dir)
    except Exception as exc:
        logger.warning("Could not load skills: %s", exc)

    # Initialize RAG collection (background)
    try:
        from rag.ingest import get_collection
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, get_collection)
        logger.info("RAG collection initialized")
    except Exception as exc:
        logger.warning("RAG init skipped: %s", exc)

    logger.info("Engine ready — listening for requests")

    # Run all handlers
    tasks = [
        asyncio.create_task(handle_chat()),
        asyncio.create_task(handle_insights()),
        asyncio.create_task(handle_expert()),
        asyncio.create_task(handle_rag()),
        asyncio.create_task(bus.heartbeat_loop(events.HEALTH_ENGINE, interval_s=5.0)),
    ]

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bus.close()
        logger.info("Engine shut down cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
