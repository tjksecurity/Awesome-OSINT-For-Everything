"""Tool registry for EVA's client-side tools.

Server-side tools (web_search, web_fetch, code_execution) are handled by
Claude's infrastructure and declared in agent.py — they don't appear here.
"""
from __future__ import annotations

from .base import Tool, ToolContext, ToolResult
from . import files, memory, osint, shell, system, voice

ALL_TOOLS: list[Tool] = [
    *files.TOOLS,
    *shell.TOOLS,
    *memory.TOOLS,
    *system.TOOLS,
    *osint.TOOLS,
    *voice.TOOLS,
]

TOOL_BY_NAME: dict[str, Tool] = {t.name: t for t in ALL_TOOLS}


def dispatch(name: str, tool_input: dict, ctx: ToolContext) -> ToolResult:
    tool = TOOL_BY_NAME.get(name)
    if tool is None:
        return ToolResult(content=f"Unknown tool: {name}", is_error=True)
    try:
        return tool.run(tool_input, ctx)
    except Exception as exc:  # noqa: BLE001 — report any failure to the model
        return ToolResult(content=f"Tool '{name}' raised: {type(exc).__name__}: {exc}", is_error=True)


def schemas_for_api(exclude_tags: tuple[str, ...] = ()) -> list[dict]:
    """Return tool schemas, optionally filtering out tools that carry any of the given tags."""
    if not exclude_tags:
        return [t.to_api_schema() for t in ALL_TOOLS]
    return [
        t.to_api_schema()
        for t in ALL_TOOLS
        if not any(tag in t.tags for tag in exclude_tags)
    ]


__all__ = [
    "Tool",
    "ToolContext",
    "ToolResult",
    "ALL_TOOLS",
    "TOOL_BY_NAME",
    "dispatch",
    "schemas_for_api",
]
