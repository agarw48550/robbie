"""Built-in semantic tools — lightweight stubs + memory lookup."""

from __future__ import annotations

import ast
import operator
import os
from datetime import datetime, timezone
from typing import Any, Optional

from src.tools.base import Tool
from src.tools.registry import ToolRegistry, default_registry

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def _eval_ast(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return float(-_eval_ast(node.operand))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        return float(_eval_ast(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return float(_BINOPS[type(node.op)](_eval_ast(node.left), _eval_ast(node.right)))
    raise ValueError("unsupported expression")


class CalculatorTool(Tool):
    name = "calculator"
    description = "Evaluate a simple arithmetic expression (e.g. 2+3*4)."

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        expr = str(arguments.get("expression") or arguments.get("expr") or "").strip()
        if not expr:
            return {"ok": False, "error": "missing expression"}
        try:
            tree = ast.parse(expr, mode="eval")
            result = _eval_ast(tree)
            return {"ok": True, "result": result, "expression": expr}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


class TimerTool(Tool):
    name = "timer"
    description = "Set a timer for N seconds (structured stub; scheduler may fire later)."

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            seconds = float(arguments.get("seconds", arguments.get("duration", 0)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid seconds"}
        label = str(arguments.get("label") or arguments.get("text") or "timer").strip()
        return {
            "ok": True,
            "result": {"seconds": max(0.0, seconds), "label": label},
            "note": "timer acknowledged (wire to Scheduler.schedule_reminder for delivery)",
        }


class CalendarTool(Tool):
    name = "calendar"
    description = "Look up or note a calendar item (stub without external calendar API)."

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "list").strip().lower()
        item = str(arguments.get("item") or arguments.get("text") or "").strip()
        when = str(arguments.get("when") or "").strip()
        return {
            "ok": True,
            "result": {"action": action, "item": item, "when": when},
            "note": "calendar stub — persist via SQLite calendar table when wired",
        }


class MemoryLookupTool(Tool):
    name = "memory_lookup"
    description = "Search remembered facts from persistence / SQLite memory."

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from src.persistence import load_memory

        query = str(arguments.get("query") or arguments.get("q") or "").strip().lower()
        mem = load_memory()
        facts = list(mem.get("facts") or [])
        if query:
            matched = [
                f
                for f in facts
                if isinstance(f, dict) and query in str(f.get("text", "")).lower()
            ]
        else:
            matched = [f for f in facts if isinstance(f, dict)][-12:]
        return {"ok": True, "result": matched, "count": len(matched)}


class InternetSearchTool(Tool):
    name = "internet_search"
    description = "Web search stub (returns structured ok without external API if no key)."

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or arguments.get("q") or "").strip()
        if not query:
            return {"ok": False, "error": "missing query"}
        api_key = os.environ.get("ROBBIE_SEARCH_API_KEY") or os.environ.get("SERPAPI_KEY")
        if not api_key:
            return {
                "ok": True,
                "result": [],
                "query": query,
                "note": "search stub — no ROBBIE_SEARCH_API_KEY / SERPAPI_KEY",
            }
        return {
            "ok": True,
            "result": [],
            "query": query,
            "note": "search key present but provider not wired yet",
        }


class WeatherTool(Tool):
    name = "weather"
    description = "Weather lookup stub (no external API if key missing)."

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        location = str(arguments.get("location") or arguments.get("city") or "").strip()
        api_key = os.environ.get("ROBBIE_WEATHER_API_KEY") or os.environ.get("OPENWEATHER_API_KEY")
        if not api_key:
            return {
                "ok": True,
                "result": {"location": location or "unknown", "summary": None},
                "note": "weather stub — no API key",
            }
        return {
            "ok": True,
            "result": {"location": location or "unknown", "summary": None},
            "note": "weather key present but provider not wired yet",
        }


class HomeworkTool(Tool):
    name = "homework"
    description = "Homework helper stub — structures a study/homework request."

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        subject = str(arguments.get("subject") or "").strip()
        question = str(arguments.get("question") or arguments.get("prompt") or "").strip()
        if not question and not subject:
            return {"ok": False, "error": "missing question or subject"}
        return {
            "ok": True,
            "result": {
                "subject": subject,
                "question": question,
                "hint": "Break the problem into steps; ask Live for a guided explanation.",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        }


class _LiveAliasTool(Tool):
    """Documentation placeholder for Live-native tools handled in live_tools.py."""

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "result": None,
            "note": (
                f"{self.name} is handled by Gemini Live (src.live_tools); "
                "not via ToolRegistry.run"
            ),
            "arguments": dict(arguments or {}),
        }


LIVE_TOOL_ALIASES: dict[str, str] = {
    "move_robot": "Move the physical robot (direction/duration/speed/expression).",
    "turn_voice_off": "Turn off voice/listening mode.",
    "remember": "Store a lasting personal fact.",
    "save_reminder": "Save a schedule item or reminder.",
    "set_voice": "Change Robbie's speaking voice.",
}


def register_builtin_tools(registry: Optional[ToolRegistry] = None) -> ToolRegistry:
    reg = registry or default_registry
    reg.register(CalculatorTool(), aliases=["calc", "math"])
    reg.register(TimerTool())
    reg.register(CalendarTool())
    reg.register(MemoryLookupTool(), aliases=["memory"])
    reg.register(InternetSearchTool(), aliases=["search"])
    reg.register(WeatherTool())
    reg.register(HomeworkTool())

    for live_name, desc in LIVE_TOOL_ALIASES.items():
        reg.register(_LiveAliasTool(live_name, desc))

    return reg


register_builtin_tools(default_registry)
