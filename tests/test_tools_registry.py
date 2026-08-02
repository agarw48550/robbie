"""Tool registry + builtin smoke tests."""

from __future__ import annotations

import asyncio

from src.tools.builtin import CalculatorTool, LIVE_TOOL_ALIASES, register_builtin_tools
from src.tools.registry import ToolRegistry


def test_registry_discover_and_aliases() -> None:
    reg = ToolRegistry()
    register_builtin_tools(reg)
    names = reg.discover()
    assert "calculator" in names
    assert "memory_lookup" in names
    assert "weather" in names
    for live_name in LIVE_TOOL_ALIASES:
        assert live_name in names
    assert reg.get("calc") is not None
    assert reg.resolve_name("search") == "internet_search"
    docs = reg.list_docs()
    assert any(d["name"] == "homework" for d in docs)


def test_calculator_tool() -> None:
    tool = CalculatorTool()
    result = asyncio.run(tool.run({"expression": "2+3*4"}))
    assert result["ok"] is True
    assert result["result"] == 14


def test_registry_run_unknown() -> None:
    reg = ToolRegistry()
    out = asyncio.run(reg.run("nope", {}))
    assert out["ok"] is False
