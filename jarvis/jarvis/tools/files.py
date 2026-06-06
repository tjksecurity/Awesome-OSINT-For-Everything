"""Local filesystem tools."""
from __future__ import annotations

import fnmatch
from pathlib import Path

from .base import Tool, ToolContext, ToolResult

MAX_READ_BYTES = 200_000
MAX_LIST_ENTRIES = 500


def _resolve(ctx: ToolContext, path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = ctx.workspace / p
    return p.resolve()


def _read_file(tool_input: dict, ctx: ToolContext) -> ToolResult:
    path_str = tool_input.get("path", "")
    if not path_str:
        return ToolResult("path is required", is_error=True)
    p = _resolve(ctx, path_str)
    if not p.exists():
        return ToolResult(f"[FAIL] no such file: {p}", is_error=True)
    if not p.is_file():
        return ToolResult(f"[FAIL] not a file: {p}", is_error=True)
    try:
        data = p.read_bytes()
    except PermissionError as e:
        return ToolResult(f"[FAIL] permission denied: {e}", is_error=True)
    if len(data) > MAX_READ_BYTES:
        head = data[:MAX_READ_BYTES].decode("utf-8", errors="replace")
        return ToolResult(
            f"{head}\n\n[truncated: file is {len(data)} bytes, showed first {MAX_READ_BYTES}]"
        )
    return ToolResult(data.decode("utf-8", errors="replace"))


def _write_file(tool_input: dict, ctx: ToolContext) -> ToolResult:
    path_str = tool_input.get("path", "")
    content = tool_input.get("content", "")
    if not path_str:
        return ToolResult("path is required", is_error=True)
    if content is None:
        return ToolResult("content is required", is_error=True)
    p = _resolve(ctx, path_str)
    overwrite = bool(tool_input.get("overwrite", False))
    if p.exists() and not overwrite:
        return ToolResult(
            f"[FAIL] {p} exists. Re-run with overwrite=true to replace.", is_error=True
        )
    detail = f"path={p}\n{len(content)} bytes\noverwrite={overwrite}"
    if not ctx.confirm_destructive("write_file", detail):
        return ToolResult("[FAIL] operator declined write_file.", is_error=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return ToolResult(f"[OK] wrote {len(content)} bytes to {p}")


def _list_dir(tool_input: dict, ctx: ToolContext) -> ToolResult:
    path_str = tool_input.get("path", ".")
    pattern = tool_input.get("pattern")
    p = _resolve(ctx, path_str)
    if not p.exists():
        return ToolResult(f"[FAIL] no such directory: {p}", is_error=True)
    if not p.is_dir():
        return ToolResult(f"[FAIL] not a directory: {p}", is_error=True)
    entries = []
    for item in sorted(p.iterdir()):
        if pattern and not fnmatch.fnmatch(item.name, pattern):
            continue
        kind = "d" if item.is_dir() else ("l" if item.is_symlink() else "f")
        try:
            size = item.stat().st_size if item.is_file() else "-"
        except OSError:
            size = "?"
        entries.append(f"{kind} {size:>10} {item.name}")
        if len(entries) >= MAX_LIST_ENTRIES:
            entries.append(f"[truncated at {MAX_LIST_ENTRIES} entries]")
            break
    if not entries:
        return ToolResult(f"[OK] {p} is empty.")
    return ToolResult(f"{p}\n" + "\n".join(entries))


def _search_files(tool_input: dict, ctx: ToolContext) -> ToolResult:
    """Recursive filename glob within the workspace."""
    pattern = tool_input.get("pattern", "")
    if not pattern:
        return ToolResult("pattern is required", is_error=True)
    root = _resolve(ctx, tool_input.get("root", "."))
    max_results = int(tool_input.get("max_results", 100))
    if not root.exists() or not root.is_dir():
        return ToolResult(f"[FAIL] not a directory: {root}", is_error=True)
    hits: list[str] = []
    for path in root.rglob(pattern):
        # Skip noisy dirs
        parts = set(path.parts)
        if parts & {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}:
            continue
        hits.append(str(path))
        if len(hits) >= max_results:
            break
    if not hits:
        return ToolResult(f"[OK] no matches for {pattern} under {root}")
    return ToolResult("\n".join(hits))


TOOLS: list[Tool] = [
    Tool(
        name="read_file",
        description=(
            "Read a UTF-8 text file from the operator's local filesystem. "
            "Returns up to 200KB; larger files are truncated with a notice. "
            "Use this freely — it is read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path, or relative to the operator's working directory."},
            },
            "required": ["path"],
        },
        run=_read_file,
        tags=["fs", "readonly"],
    ),
    Tool(
        name="write_file",
        description=(
            "Write a text file on the operator's filesystem. The operator will be "
            "prompted for confirmation before the write is performed. "
            "Set overwrite=true to replace an existing file."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "overwrite": {"type": "boolean", "default": False},
            },
            "required": ["path", "content"],
        },
        run=_write_file,
        tags=["fs", "destructive"],
    ),
    Tool(
        name="list_dir",
        description="List the contents of a directory on the operator's machine. Read-only.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "pattern": {"type": "string", "description": "Optional fnmatch pattern, e.g. '*.py'"},
            },
        },
        run=_list_dir,
        tags=["fs", "readonly"],
    ),
    Tool(
        name="search_files",
        description=(
            "Recursively find files by glob pattern under a root directory. "
            "Skips .git, node_modules, __pycache__, .venv. Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob, e.g. '**/*.md' or 'README*'"},
                "root": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "default": 100},
            },
            "required": ["pattern"],
        },
        run=_search_files,
        tags=["fs", "readonly"],
    ),
]
