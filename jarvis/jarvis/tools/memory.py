"""Persistent memory tools — remember/recall/forget across sessions."""
from __future__ import annotations

from .base import Tool, ToolContext, ToolResult


def _remember(tool_input: dict, ctx: ToolContext) -> ToolResult:
    key = tool_input.get("key", "").strip()
    value = tool_input.get("value", "").strip()
    tags = tool_input.get("tags") or []
    if not key:
        return ToolResult("key is required", is_error=True)
    if not value:
        return ToolResult("value is required", is_error=True)
    entry = ctx.memory.remember(key, value, tags=tags)
    tagstr = f" [{', '.join(entry.tags)}]" if entry.tags else ""
    return ToolResult(f"[OK] remembered: {entry.key} = {entry.value}{tagstr}")


def _recall(tool_input: dict, ctx: ToolContext) -> ToolResult:
    query = tool_input.get("query")
    tag = tool_input.get("tag")
    results = ctx.memory.recall(query=query, tag=tag)
    if not results:
        return ToolResult("[OK] no matching memory.")
    lines = []
    for e in results[:50]:
        tagstr = f" [{', '.join(e.tags)}]" if e.tags else ""
        lines.append(f"- {e.key}: {e.value}{tagstr}")
    return ToolResult("\n".join(lines))


def _forget(tool_input: dict, ctx: ToolContext) -> ToolResult:
    key = tool_input.get("key", "").strip()
    if not key:
        return ToolResult("key is required", is_error=True)
    ok = ctx.memory.forget(key)
    return ToolResult(f"[OK] forgot: {key}" if ok else f"[OK] no such memory: {key}")


TOOLS: list[Tool] = [
    Tool(
        name="remember",
        description=(
            "Store a fact about the operator that should persist across sessions. "
            "Use a short stable key (e.g. 'editor', 'github_user', 'main_project_path'). "
            "Re-storing the same key updates the value. Use this whenever you learn "
            "something durable about the operator."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short stable identifier."},
                "value": {"type": "string", "description": "The fact to remember."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags."},
            },
            "required": ["key", "value"],
        },
        run=_remember,
        tags=["memory"],
    ),
    Tool(
        name="recall",
        description="Search the operator's persistent memory. Pass query OR tag (or neither for a full dump).",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring match across key, value, tags."},
                "tag": {"type": "string", "description": "Filter to entries with this tag."},
            },
        },
        run=_recall,
        tags=["memory", "readonly"],
    ),
    Tool(
        name="forget",
        description="Delete a memory entry by key.",
        input_schema={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        run=_forget,
        tags=["memory"],
    ),
]
