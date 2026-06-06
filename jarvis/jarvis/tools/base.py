from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config
    from ..memory import MemoryStore


@dataclass
class ToolContext:
    """Runtime context passed to every tool invocation."""
    config: "Config"
    memory: "MemoryStore"
    workspace: Path
    confirm_destructive: Callable[[str, str], bool]
    """confirm_destructive(action: str, detail: str) -> bool — prompt operator for go/no-go."""


@dataclass
class ToolResult:
    content: str
    is_error: bool = False


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    run: Callable[[dict, ToolContext], ToolResult]
    tags: list[str] = field(default_factory=list)

    def to_api_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
