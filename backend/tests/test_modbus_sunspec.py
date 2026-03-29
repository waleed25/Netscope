"""
Tests for backend/modbus/sunspec.py

Covers:
  - SunSpecClient.discover(): no marker, marker at 40000, connection error,
    immediate sentinel
  - apply_scale_factors(): basic SF application, no SF present
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from modbus.sunspec import SunSpecClient, apply_scale_factors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(registers: list[int]) -> MagicMock:
    """Create a mock Modbus response with .registers and .isError() == False."""
    resp = MagicMock()
    resp.registers = registers
    resp.isError.return_value = False
    return resp


def _make_error_response() -> MagicMock:
    """Create a mock Modbus response that represents an error."""
    resp = MagicMock()
    resp.isError.return_value = True
    return resp


# ---------------------------------------------------------------------------
# Test 1: No SunSpec marker at any base address
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_no_marker():
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock(return_value=True)
    mock_client.close = MagicMock()
    # All reads return [0x0000, 0x0000] — not the marker
    mock_client.read_holding_registers = AsyncMock(
        return_value=_make_response([0x0000, 0x0000])
    )

    with patch("modbus.sunspec.AsyncModbusTcpClient", return_value=mock_client):
        result = await SunSpecClient.discover("127.0.0.1")

    assert result == {"found": False, "base_address": None, "models": []}


# ---------------------------------------------------------------------------
# Test 2: Marker found at 40000, one model (Common, DID=1), then sentinel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_finds_marker_at_40000():
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock(return_value=True)
    mock_client.close = MagicMock()

    # Call sequence:
    # 1. addr=40000, count=2  → marker [0x5375, 0x6E53]
    # 2. addr=40002, count=2  → [DID=1, Length=66]
    # 3. addr=40004, count=66 → 66 zero registers (model data)
    # 4. addr=40072, count=2  → [0xFFFF, 0x0000]  sentinel
    read_results = [
        _make_response([0x5375, 0x6E53]),
        _make_response([0x0001, 0x0042]),
        _make_response([0] * 66),
        _make_response([0xFFFF, 0x0000]),
    ]
    mock_client.read_holding_registers = AsyncMock(side_effect=read_results)

    with patch("modbus.sunspec.AsyncModbusTcpClient", return_value=mock_client):
        result = await SunSpecClient.discover("127.0.0.1")

    assert result["found"] is True
    assert result["base_address"] == 40000
    assert len(result["models"]) == 1
    model = result["models"][0]
    assert model["did"] == 1
    assert model["name"] == "Common"
    assert model["length"] == 66
    assert model["base_addr"] == 40002  # addr after marker (40000 + 2)


# ---------------------------------------------------------------------------
# Test 3: Connection error — should return empty result, not propagate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_connection_error():
    with patch(
        "modbus.sunspec.AsyncModbusTcpClient",
        side_effect=ConnectionRefusedError("Connection refused"),
    ):
        result = await SunSpecClient.discover("127.0.0.1")

    assert result == {"found": False, "base_address": None, "models": []}


# ---------------------------------------------------------------------------
# Test 4: Marker found, but sentinel immediately follows (no models)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_sentinel_immediately():
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock(return_value=True)
    mock_client.close = MagicMock()

    read_results = [
        _make_response([0x5375, 0x6E53]),   # marker at 40000
        _make_response([0xFFFF, 0x0000]),   # immediate sentinel at 40002
    ]
    mock_client.read_holding_registers = AsyncMock(side_effect=read_results)

    with patch("modbus.sunspec.AsyncModbusTcpClient", return_value=mock_client):
        result = await SunSpecClient.discover("127.0.0.1")

    assert result["found"] is True
    assert result["models"] == []


# ---------------------------------------------------------------------------
# Test 5: apply_scale_factors — basic SF application
# ---------------------------------------------------------------------------

def test_apply_scale_factors_basic():
    # Voltage = 2300, Voltage_SF = -2 (as uint16: 0xFFFE = 65534)
    # Signed int16 of 0xFFFE = -2
    sf_raw = 0xFFFE  # uint16 representation of -2
    registers = {0: 2300, 1: sf_raw}
    model_registers = [(0, "Voltage"), (1, "Voltage_SF")]

    result = apply_scale_factors(registers, model_registers)

    assert "Voltage" in result
    assert result["Voltage"]["raw"] == 2300
    assert abs(result["Voltage"]["scaled"] - 23.0) < 1e-9
    assert result["Voltage"]["sf_applied"] is True


# ---------------------------------------------------------------------------
# Test 6: apply_scale_factors — no scale factor present
# ---------------------------------------------------------------------------

def test_apply_scale_factors_no_sf():
    registers = {0: 100}
    model_registers = [(0, "Status")]

    result = apply_scale_factors(registers, model_registers)

    assert "Status" in result
    assert result["Status"]["raw"] == 100
    assert result["Status"]["sf_applied"] is False
