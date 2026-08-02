"""Tool registry — register, get, discover, list docs."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from src.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._aliases: dict[str, str] = {}

    def register(self, tool: Tool, *, aliases: Optional[Iterable[str]] = None) -> None:
        if not tool.name:
            raise ValueError("Tool.name is required")
        self._tools[tool.name] = tool
        for alias in aliases or ():
            self._aliases[str(alias)] = tool.name

    def get(self, name: str) -> Optional[Tool]:
        if name in self._tools:
            return self._tools[name]
        canonical = self._aliases.get(name)
        if canonical:
            return self._tools.get(canonical)
        return None

    def discover(self) -> list[str]:
        """Return registered tool names (canonical, sorted)."""
        return sorted(self._tools.keys())

    def list_docs(self) -> list[dict[str, str]]:
        docs = [t.docs() for t in self._tools.values()]
        docs.sort(key=lambda d: d.get("name", ""))
        return docs

    def resolve_name(self, name: str) -> Optional[str]:
        if name in self._tools:
            return name
        return self._aliases.get(name)

    async def run(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        tool = self.get(name)
        if tool is None:
            return {"ok": False, "error": f"unknown tool {name}"}
        return await tool.run(dict(arguments or {}))


# Module-level registry populated by ``src.tools.builtin``
default_registry = ToolRegistry()
