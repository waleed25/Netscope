"""Tests for the 5 new Modbus LLM chat tools."""
from __future__ import annotations
import asyncio
import importlib
import importlib.util
import os
import sys
import types
import unittest
from dataclasses import dataclass, field
from typing import Callable, Set
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helper: create stub modules
# ---------------------------------------------------------------------------

def _stub(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


# ---------------------------------------------------------------------------
# Stub all third-party / internal packages that modbus.py imports
# ---------------------------------------------------------------------------

for _pkg in (
    "modbus",
    "modbus.diagnostics",
    "modbus.simulator",
    "modbus.client",
    "modbus.waveforms",
    "modbus.sunspec",
    "modbus.register_maps",
    "modbus.scanner",
    "modbus.wireshark_analyzer",
    "modbus.device_loader",
    "utils",
    "utils.proc",
    "utils.tshark_utils",
    "utils.toon",
    "utils.sanitize",
):
    _stub(_pkg)

# ---------------------------------------------------------------------------
# Stub the registry (agent.tools.registry) BEFORE importing modbus.py
# ---------------------------------------------------------------------------

_TOOL_REGISTRY: dict = {}


def _register(tool):
    _TOOL_REGISTRY[tool.name] = tool
    return tool


@dataclass
class ToolDef:
    name: str
    category: str
    description: str
    args_spec: str
    runner: Callable
    safety: str = "safe"
    keywords: Set[str] = field(default_factory=set)
    always_available: bool = False
    needs_packets: bool = False
    is_workflow: bool = False


_registry_mod = types.ModuleType("agent.tools.registry")
_registry_mod.register = _register
_registry_mod.ToolDef = ToolDef
_registry_mod.TOOL_REGISTRY = _TOOL_REGISTRY
_registry_mod.MAX_OUTPUT = 3000
sys.modules["agent.tools.registry"] = _registry_mod

_audit_mod = types.ModuleType("agent.tools.audit")
_audit_mod.get_audit_log = lambda: MagicMock()
sys.modules["agent.tools.audit"] = _audit_mod

# ---------------------------------------------------------------------------
# Build agent / agent.tools as real packages pointing at the right __path__
# ---------------------------------------------------------------------------

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# "agent" package
_agent_pkg = types.ModuleType("agent")
_agent_pkg.__path__ = [os.path.join(_BACKEND_DIR, "agent")]
_agent_pkg.__package__ = "agent"
sys.modules["agent"] = _agent_pkg

# "agent.tools" package — needs real __path__ so sub-module import works
_agent_tools_pkg = types.ModuleType("agent.tools")
_agent_tools_pkg.__path__ = [os.path.join(_BACKEND_DIR, "agent", "tools")]
_agent_tools_pkg.__package__ = "agent.tools"
_agent_pkg.tools = _agent_tools_pkg
sys.modules["agent.tools"] = _agent_tools_pkg

# ---------------------------------------------------------------------------
# Now load agent/tools/modbus.py directly via spec
# ---------------------------------------------------------------------------

_modbus_path = os.path.join(_BACKEND_DIR, "agent", "tools", "modbus.py")
_spec = importlib.util.spec_from_file_location(
    "agent.tools.modbus", _modbus_path,
    submodule_search_locations=[],
)
modbus_tools = importlib.util.module_from_spec(_spec)
modbus_tools.__package__ = "agent.tools"
sys.modules["agent.tools.modbus"] = modbus_tools
_spec.loader.exec_module(modbus_tools)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# 1. modbus_diagnostics — formats summary with RTT and Exceptions
# ===========================================================================

class TestModbusDiagnosticsFormatsSummary(unittest.TestCase):
    def test_modbus_diagnostics_formats_summary(self):
        mock_stats = {
            "rtt": {"avg": 12.0, "p50": 9.0, "p95": 34.0, "p99": 67.0},
            "exceptions": [
                {"fc": 3, "addr": 40001, "ec": 2, "count": 12},
                {"fc": 3, "addr": 40002, "ec": 6, "count": 4},
                {"fc": 3, "addr": 40003, "ec": 4, "count": 1},
            ],
            "heatmap": {"40001": 1284},
            "timeline": [],
            "transactions": [
                {"seq": 1, "fc": 3, "addr": 40001, "rtt_ms": 10.0,
                 "status": "ok", "ec": None, "response": "[100]"},
                {"seq": 2, "fc": 3, "addr": 40002, "rtt_ms": 15.0,
                 "status": "exception", "ec": 2, "response": "EC02"},
            ],
            "req_rate": 1.2,
            "total_polls": 1284,
        }
        mock_engine = MagicMock()
        mock_engine.get_stats.return_value = mock_stats

        mock_diag_mod = MagicMock()
        mock_diag_mod.diagnostics_engine = mock_engine

        with unittest.mock.patch.dict("sys.modules", {"modbus.diagnostics": mock_diag_mod}):
            result = run(modbus_tools.run_modbus_diagnostics("sim-001"))

        self.assertIn("RTT", result)
        self.assertIn("Exceptions", result)
        self.assertIn("sim-001", result)
        self.assertIn("1284", result)
        mock_engine.get_stats.assert_called_once_with("sim-001")


# ===========================================================================
# 2. modbus_write_multi FC16 — dispatched to client write_registers
# ===========================================================================

class TestModbusWriteMultiFc16(unittest.TestCase):
    def test_modbus_write_multi_fc16(self):
        mock_session = MagicMock()
        mock_session.write_registers = AsyncMock(return_value={"ok": True})

        mock_client_manager = MagicMock()
        mock_client_manager.get_session.return_value = mock_session

        mock_sim_manager = MagicMock()
        mock_sim_manager.get_session.return_value = None

        mock_sim_mod = MagicMock()
        mock_sim_mod.simulator_manager = mock_sim_manager

        mock_cli_mod = MagicMock()
        mock_cli_mod.client_manager = mock_client_manager

        with unittest.mock.patch.dict("sys.modules", {
            "modbus.simulator": mock_sim_mod,
            "modbus.client": mock_cli_mod,
        }):
            result = run(modbus_tools.run_modbus_write_multi("sim-001 16 40010 100 200 300"))

        mock_session.write_registers.assert_called_once_with(40010, [100, 200, 300])
        self.assertIn("ok", result.lower())


# ===========================================================================
# 3. modbus_sunspec_discover — response contains "DID 1"
# ===========================================================================

class TestModbusSunspecDiscoverFound(unittest.TestCase):
    def test_modbus_sunspec_discover_found(self):
        mock_discover_result = {
            "found": True,
            "base_address": 40000,
            "models": [
                {"did": 1, "name": "Common", "length": 66, "registers": {}},
            ],
        }
        mock_client_cls = MagicMock()
        mock_client_cls.discover = AsyncMock(return_value=mock_discover_result)

        mock_sunspec_mod = MagicMock()
        mock_sunspec_mod.SunSpecClient = mock_client_cls

        with unittest.mock.patch.dict("sys.modules", {"modbus.sunspec": mock_sunspec_mod}):
            result = run(modbus_tools.run_modbus_sunspec_discover("192.168.1.10"))

        self.assertIn("DID 1", result)
        self.assertIn("Common", result)
        mock_client_cls.discover.assert_called_once_with("192.168.1.10", 502, 1)


# ===========================================================================
# 4. modbus_set_waveform — sine params parsed and set_waveform called
# ===========================================================================

class TestModbusSetWaveformSine(unittest.TestCase):
    def test_modbus_set_waveform_sine(self):
        mock_sine_instance = MagicMock()
        mock_sine_cls = MagicMock(return_value=mock_sine_instance)

        mock_sim_manager = MagicMock()
        mock_sim_manager.set_waveform.return_value = True

        mock_waveforms_mod = MagicMock()
        mock_waveforms_mod.SineWave = mock_sine_cls

        mock_sim_mod = MagicMock()
        mock_sim_mod.simulator_manager = mock_sim_manager

        with unittest.mock.patch.dict("sys.modules", {
            "modbus.waveforms": mock_waveforms_mod,
            "modbus.simulator": mock_sim_mod,
        }):
            result = run(modbus_tools.run_modbus_set_waveform(
                "sim-001 40001 sine amplitude=500 period_s=5"
            ))

        mock_sine_cls.assert_called_once_with(
            amplitude=500.0, period_s=5.0, phase_rad=0.0, dc_offset=1000.0
        )
        mock_sim_manager.set_waveform.assert_called_once_with("sim-001", 40001, mock_sine_instance)
        self.assertIn("ok", result.lower())


# ===========================================================================
# 5. modbus_inject_exception — set_exception_rule called with rate=0.2
# ===========================================================================

class TestModbusInjectExceptionCallsApi(unittest.TestCase):
    def test_modbus_inject_exception_calls_api(self):
        mock_sim_manager = MagicMock()
        mock_sim_manager.set_exception_rule.return_value = True

        mock_sim_mod = MagicMock()
        mock_sim_mod.simulator_manager = mock_sim_manager

        with unittest.mock.patch.dict("sys.modules", {"modbus.simulator": mock_sim_mod}):
            result = run(modbus_tools.run_modbus_inject_exception("sim-001 40100 2 0.2"))

        mock_sim_manager.set_exception_rule.assert_called_once_with("sim-001", 40100, 2, 0.2)
        self.assertIn("ok", result.lower())


if __name__ == "__main__":
    unittest.main()
