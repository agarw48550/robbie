"""Semantic tool framework for Robbie (registry + builtins)."""

from __future__ import annotations

from src.tools.base import Tool
from src.tools.registry import ToolRegistry, default_registry

# Side-effect: register built-in + Live alias tools on import
from src.tools import builtin as _builtin  # noqa: F401

__all__ = ["Tool", "ToolRegistry", "default_registry"]
