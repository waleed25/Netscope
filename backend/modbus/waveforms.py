"""Waveform generators for Modbus register simulation.

Each generator produces uint16 register values (0–65535) as a function
of time t (float, seconds since start).
"""

from __future__ import annotations

import ast
import math
import random as _random

_SAFE_GLOBALS: dict = {
    "math": math,
    "random": _random,
    "abs": abs,
    "int": int,
    "min": min,
    "max": max,
    "round": round,
    "__builtins__": {},
}

_BLOCKED_CALLS = {
    "__import__", "open", "exec", "eval", "compile", 
    "getattr", "setattr", "delattr", "type", "isinstance",
    "vars", "dir", "globals", "locals", "hasattr",
    "id", "callable", "repr", "chr", "ord", "hex", "oct", "bin",
}
_BLOCKED_ATTR_OBJECTS = {"os", "sys", "subprocess", "builtins"}


def _clamp_uint16(value: float) -> int:
    """Clamp a float to [0, 65535] and return as int."""
    return int(max(0, min(65535, value)))


class SineWave:
    """Sinusoidal waveform generator."""

    def __init__(
        self,
        amplitude: float,
        period_s: float,
        phase_rad: float = 0.0,
        dc_offset: float = 0.0,
    ) -> None:
        if period_s == 0:
            raise ValueError("period_s must be non-zero")
        self.amplitude = amplitude
        self.period_s = period_s
        self.phase_rad = phase_rad
        self.dc_offset = dc_offset

    def tick(self, t: float) -> int:
        """Return uint16 register value at time t seconds."""
        raw = self.dc_offset + self.amplitude * math.sin(
            2 * math.pi * t / self.period_s + self.phase_rad
        )
        return _clamp_uint16(raw)


class Ramp:
    """Linearly incrementing ramp that wraps between min_val and max_val."""

    def __init__(self, start: int, step: int, min_val: int, max_val: int) -> None:
        if step == 0:
            raise ValueError("step must be non-zero")
        if step < 0:
            raise ValueError("step must be positive")
        if not (min_val <= start <= max_val):
            raise ValueError(f"start ({start}) must be in [{min_val}, {max_val}]")
        self.step = step
        self.min_val = min_val
        self.max_val = max_val
        self._current = start

    def tick(self, t: float) -> int:  # noqa: ARG002
        """Return the current counter value, then advance by step (wrapping at max_val)."""
        value = self._current
        next_val = self._current + self.step
        if next_val > self.max_val:
            next_val = self.min_val
        self._current = next_val
        return int(max(self.min_val, min(self.max_val, value)))


class _ASTValidator(ast.NodeVisitor):
    """Walk an expression AST and raise ValueError on disallowed constructs."""

    _BLOCKED_ATTR_OBJECTS = _BLOCKED_ATTR_OBJECTS

    def visit_Call(self, node: ast.Call) -> None:
        # Block specific dangerous function names
        func = node.func
        name: str | None = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name in _BLOCKED_CALLS:
            raise ValueError(f"Disallowed function call in expression: {name!r}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Block dunder attribute names (e.g., .__class__, .__mro__, .__bases__)
        if isinstance(node.attr, str) and node.attr.startswith("__"):
            raise ValueError(f"Unsafe attribute access: .{node.attr}")
        # Block access on known dangerous base objects
        if isinstance(node.value, ast.Name) and node.value.id in self._BLOCKED_ATTR_OBJECTS:
            raise ValueError(
                f"Disallowed attribute access on {node.value.id!r} in expression"
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # Block dunder names
        if node.id.startswith("__"):
            raise ValueError(f"Disallowed name in expression: {node.id!r}")
        self.generic_visit(node)


class ScriptWave:
    """Waveform defined by an arbitrary Python expression evaluated at each tick.

    Security: the expression is validated via AST inspection at construction
    time and evaluated with a restricted globals dict (no builtins).
    """

    def __init__(self, expression: str) -> None:
        # Fail fast on syntax errors and dangerous constructs
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"Invalid expression syntax: {exc}") from exc

        _ASTValidator().visit(tree)
        self._code = compile(tree, "<scriptwave>", "eval")
        self._expression = expression

    def tick(self, t: float) -> int:
        """Evaluate the expression with t substituted and return a uint16 value."""
        result = eval(self._code, dict(_SAFE_GLOBALS), {"t": t})  # noqa: S307
        try:
            raw = float(result)
        except (TypeError, ValueError):
            raise ValueError(f"Expression did not return a numeric value: {result!r}")
        return _clamp_uint16(raw)
