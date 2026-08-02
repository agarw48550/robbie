"""Common Tool interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Base class for semantic / utility tools."""

    name: str = ""
    description: str = ""

    @abstractmethod
    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool. Return a structured ``{ok, ...}`` dict."""

    def docs(self) -> dict[str, str]:
        return {"name": self.name, "description": self.description}
