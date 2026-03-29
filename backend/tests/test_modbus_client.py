"""
Tests for modbus/client.py — RTT measurement, delta tracking, and write FCs.
All pymodbus network calls are mocked; no real connections are made.
"""
from __future__ import annotations
import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend package root is on path (conftest does this too, but be explicit)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modbus.register_maps import RegisterDef
from modbus.client import ClientSession
from modbus.diagnostics import DiagnosticsEngine


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_session(registers=None) -> ClientSession:
    """Build a ClientSession without starting the poll loop."""
    if registers is None:
        registers = [
            RegisterDef(address=100, name="Voltage", unit="V", scale=1.0,
                        data_type="uint16", access="ro")
        ]
    return ClientSession(
        session_id="test-sess",
        label="test",
        host="127.0.0.1",
        port=502,
        unit_id=1,
        registers=registers,
    )


def _ok_response(values: list[int]) -> MagicMock:
    """Fake pymodbus response that looks like a successful read."""
    resp = MagicMock()
    resp.isError.return_value = False
    resp.registers = values
    return resp


def _error_response(exception_code: int | None = None) -> MagicMock:
    """Fake pymodbus response that looks like an error."""
    resp = MagicMock()
    resp.isError.return_value = True
    resp.exception_code = exception_code
    return resp


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rtt_recorded_on_poll():
    """After a successful FC3 read, diagnostics_engine.record() is called with rtt_ms > 0."""
    session = _make_session()

    # Fresh DiagnosticsEngine so we can inspect it cleanly
    fresh_engine = DiagnosticsEngine()

    mock_client = MagicMock()
    mock_client.connected = True
    mock_client.read_holding_registers = AsyncMock(return_value=_ok_response([42]))
    session._client = mock_client

    with patch("modbus.client.diagnostics_engine", fresh_engine):
        await session._poll_once()

    stats = fresh_engine.get_stats("test-sess")
    assert stats["total_polls"] == 1
    assert stats["rtt"]["avg"] > 0, "RTT should be positive"
    assert len(stats["transactions"]) == 1
    txn = stats["transactions"][0]
    assert txn["rtt_ms"] >= 0
    assert txn["status"] == "ok"
    assert txn["fc"] == 3


@pytest.mark.asyncio
async def test_delta_tracked_between_polls():
    """After two polls with different values, _prev_values updates and delta is non-zero."""
    session = _make_session()

    mock_client = MagicMock()
    mock_client.connected = True
    session._client = mock_client

    fresh_engine = DiagnosticsEngine()

    with patch("modbus.client.diagnostics_engine", fresh_engine):
        # First poll — value = 100
        mock_client.read_holding_registers = AsyncMock(return_value=_ok_response([100]))
        result1 = await session._poll_once()

        # After first poll _prev_values should hold 100
        assert session._prev_values.get(100) == 100  # address 100

        # Second poll — value = 150
        mock_client.read_holding_registers = AsyncMock(return_value=_ok_response([150]))
        result2 = await session._poll_once()

    assert session._prev_values.get(100) == 150

    # The second result should show delta = 150 - 100 = 50
    entry2 = result2[0]
    assert "error" not in entry2
    assert entry2["delta"] == 50

    # First result has delta = 0 (no previous value)
    entry1 = result1[0]
    assert entry1["delta"] == 0


@pytest.mark.asyncio
async def test_write_register_fc06_ok():
    """write_register (FC06) returns {"ok": True, ...} on a successful write."""
    session = _make_session()

    mock_client = MagicMock()
    mock_client.connected = True
    mock_write_resp = MagicMock()
    mock_write_resp.isError.return_value = False
    mock_client.write_register = AsyncMock(return_value=mock_write_resp)
    session._client = mock_client

    fresh_engine = DiagnosticsEngine()

    with patch("modbus.client.diagnostics_engine", fresh_engine):
        result = await session.write_register(address=200, value=1234)

    assert result["ok"] is True
    assert result["address"] == 200
    assert result["value"] == 1234

    # Diagnostics recorded
    stats = fresh_engine.get_stats("test-sess")
    assert stats["total_polls"] == 1
    txn = stats["transactions"][0]
    assert txn["fc"] == 6
    assert txn["status"] == "ok"


@pytest.mark.asyncio
async def test_write_registers_fc16_ok():
    """write_registers (FC16) returns {"ok": True, "values": [...]} on success."""
    session = _make_session()

    mock_client = MagicMock()
    mock_client.connected = True
    mock_write_resp = MagicMock()
    mock_write_resp.isError.return_value = False
    mock_client.write_registers = AsyncMock(return_value=mock_write_resp)
    session._client = mock_client

    fresh_engine = DiagnosticsEngine()
    values = [10, 20, 30]

    with patch("modbus.client.diagnostics_engine", fresh_engine):
        result = await session.write_registers(address=300, values=values)

    assert result["ok"] is True
    assert result["address"] == 300
    assert result["values"] == values

    stats = fresh_engine.get_stats("test-sess")
    assert stats["total_polls"] == 1
    txn = stats["transactions"][0]
    assert txn["fc"] == 16
    assert txn["status"] == "ok"


@pytest.mark.asyncio
async def test_write_coil_fc05_ok():
    """write_coil (FC05) returns {"ok": True, ...} on a successful coil write."""
    session = _make_session()

    mock_client = MagicMock()
    mock_client.connected = True
    mock_write_resp = MagicMock()
    mock_write_resp.isError.return_value = False
    mock_client.write_coil = AsyncMock(return_value=mock_write_resp)
    session._client = mock_client

    fresh_engine = DiagnosticsEngine()

    with patch("modbus.client.diagnostics_engine", fresh_engine):
        result = await session.write_coil(address=0, value=True)

    assert result["ok"] is True
    assert result["address"] == 0
    assert result["value"] is True

    stats = fresh_engine.get_stats("test-sess")
    assert stats["total_polls"] == 1
    txn = stats["transactions"][0]
    assert txn["fc"] == 5
    assert txn["status"] == "ok"
