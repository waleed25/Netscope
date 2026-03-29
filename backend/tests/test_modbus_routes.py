"""
Tests for the new Modbus God's View endpoints in api/modbus_routes.py.

Covers:
  1. GET  /api/modbus/diagnostics/{session_id}  — empty / unknown session
  2. GET  /api/modbus/{source}/{session_id}/registers  — invalid source → 400
  3. POST /api/modbus/sunspec/discover  — connection refused → {"found": false}
  4. POST /api/modbus/simulator/{session_id}/waveform  — unknown session → 404
  5. POST /api/modbus/simulator/{session_id}/exception_rule  — unknown session → 404
"""

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

# Build a minimal app that includes just the modbus router so we don't
# need the full FastAPI lifespan (ChromaDB, Ollama, etc.).
from api.modbus_routes import router as modbus_router

app = FastAPI()
app.include_router(modbus_router, prefix="/api")

client = TestClient(app, raise_server_exceptions=False)


# ── 1. Diagnostics — empty / unknown session ──────────────────────────────────

def test_get_diagnostics_empty_session():
    """Unknown session should return 200 with rtt.avg == 0 (no data recorded)."""
    resp = client.get("/api/modbus/diagnostics/unknown-session")
    assert resp.status_code == 200
    data = resp.json()
    assert "rtt" in data
    assert data["rtt"]["avg"] == 0.0


# ── 2. Generic registers endpoint — invalid source ────────────────────────────

def test_get_registers_invalid_source():
    """Source other than 'simulator'/'client' should return 400."""
    resp = client.get("/api/modbus/invalid/some-session/registers")
    assert resp.status_code == 400


# ── 3. SunSpec discover — connection refused ──────────────────────────────────

def test_sunspec_discover_connection_refused():
    """
    Connecting to a port that is (almost certainly) closed should not raise —
    SunSpecClient.discover() swallows exceptions and returns {"found": False, ...}.
    """
    resp = client.post(
        "/api/modbus/sunspec/discover",
        json={"host": "127.0.0.1", "port": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is False


# ── 4. Waveform — unknown session ─────────────────────────────────────────────

def test_set_waveform_unknown_session():
    """Posting a waveform to a non-existent session should return 404."""
    resp = client.post(
        "/api/modbus/simulator/unknown/waveform",
        json={
            "addr": 40001,
            "waveform_type": "sine",
            "amplitude": 500.0,
            "period_s": 5.0,
        },
    )
    assert resp.status_code == 404


# ── 5. Exception rule — unknown session ───────────────────────────────────────

def test_set_exception_rule_unknown_session():
    """Posting an exception rule to a non-existent session should return 404."""
    resp = client.post(
        "/api/modbus/simulator/unknown/exception_rule",
        json={
            "addr": 40001,
            "exception_code": 2,
            "rate": 0.5,
        },
    )
    assert resp.status_code == 404
