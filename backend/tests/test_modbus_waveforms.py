"""Tests for backend/modbus/waveforms.py — SineWave, Ramp, ScriptWave."""

import pytest

from modbus.waveforms import Ramp, ScriptWave, SineWave


# ---------------------------------------------------------------------------
# SineWave
# ---------------------------------------------------------------------------


def test_sine_wave_dc_offset():
    """Zero amplitude returns exactly dc_offset."""
    w = SineWave(amplitude=0, period_s=1, dc_offset=100)
    assert w.tick(0) == 100


def test_sine_wave_peak():
    """Quarter period with amplitude=1000 and dc_offset=1000 should reach ~2000."""
    w = SineWave(amplitude=1000, period_s=4, dc_offset=1000)
    result = w.tick(1.0)  # t=1 → quarter period → sin = 1 → peak
    assert abs(result - 2000) <= 5, f"Expected ~2000, got {result}"


def test_sine_wave_clamp_low():
    """Negative raw value is clamped to 0."""
    w = SineWave(amplitude=0, period_s=1, dc_offset=-5000)
    assert w.tick(0) == 0


def test_sine_wave_clamp_high():
    """Value above 65535 is clamped to 65535."""
    w = SineWave(amplitude=0, period_s=1, dc_offset=70000)
    assert w.tick(0) == 65535


# ---------------------------------------------------------------------------
# Ramp
# ---------------------------------------------------------------------------


def test_ramp_increments():
    """First 11 ticks produce [0, 10, 20, ..., 100]."""
    r = Ramp(start=0, step=10, min_val=0, max_val=100)
    results = [r.tick(float(i)) for i in range(11)]
    assert results == list(range(0, 101, 10))


def test_ramp_wraps():
    """After reaching max_val the next tick wraps back to min_val."""
    r = Ramp(start=0, step=10, min_val=0, max_val=100)
    # Consume the first 11 values (0..100)
    for _ in range(11):
        r.tick(0.0)
    # 12th call should wrap to min_val = 0
    assert r.tick(0.0) == 0


# ---------------------------------------------------------------------------
# ScriptWave
# ---------------------------------------------------------------------------


def test_scriptwave_constant():
    """Constant expression returns correct value."""
    w = ScriptWave("42")
    assert w.tick(0) == 42


def test_scriptwave_uses_t():
    """Expression can reference t."""
    w = ScriptWave("int(t * 10)")
    assert w.tick(5.0) == 50


def test_scriptwave_uses_math():
    """Expression can use the math module."""
    w = ScriptWave("int(math.sin(math.pi/2) * 100)")
    assert w.tick(0) == 100


def test_scriptwave_blocks_import():
    """__import__ is rejected at construction time."""
    with pytest.raises(ValueError):
        ScriptWave("__import__('os')")


def test_scriptwave_blocks_open():
    """open() is rejected at construction time."""
    with pytest.raises(ValueError):
        ScriptWave("open('/etc/passwd')")


def test_scriptwave_clamp():
    """Values above 65535 are clamped."""
    w = ScriptWave("100000")
    assert w.tick(0) == 65535


def test_sine_wave_zero_period_raises():
    with pytest.raises(ValueError):
        SineWave(amplitude=100, period_s=0)


def test_ramp_zero_step_raises():
    with pytest.raises(ValueError):
        Ramp(start=0, step=0, min_val=0, max_val=100)


def test_ramp_negative_step_raises():
    with pytest.raises(ValueError):
        Ramp(start=0, step=-1, min_val=0, max_val=100)


def test_ramp_start_out_of_range_raises():
    with pytest.raises(ValueError):
        Ramp(start=200, step=1, min_val=0, max_val=100)


def test_scriptwave_blocks_dunder_attr():
    with pytest.raises(ValueError):
        ScriptWave("(1).__class__")


def test_scriptwave_fresh_globals():
    # Two separate ScriptWave instances — second must not see poisoned globals from first
    w1 = ScriptWave("42")
    w2 = ScriptWave("int(t)")
    w1.tick(0)  # trigger first eval (CPython would poison shared globals)
    assert w2.tick(7.0) == 7  # must work correctly
