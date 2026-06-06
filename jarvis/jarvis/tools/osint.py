"""OSINT lookups against the repo's Awesome-OSINT-For-Everything README.

This is a sub-capability that takes advantage of being hosted inside the
tjksecurity/Awesome-OSINT-For-Everything repository: EVA can recommend the
right OSINT tools from the curated list when the operator gives a target.
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import Tool, ToolContext, ToolResult

# Markdown link parser — captures [name](url) optionally followed by a description on the same line.
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)\s*[-–:]?\s*(.*)")

MAX_HITS = 25


def _find_readme(start: Path) -> Path | None:
    """Walk up looking for the OSINT README."""
    here = start.resolve()
    candidates = [here, *here.parents]
    for d in candidates:
        # The repo's main file is at the root
        for name in ("README.md", "Readme.md", "readme.md"):
            r = d / name
            if r.exists() and r.stat().st_size > 1000:
                text = r.read_text(errors="replace")[:2000].lower()
                if "osint" in text or "open source intelligence" in text:
                    return r
    return None


def _parse_section(text: str) -> list[dict]:
    """Extract tool entries from the README. Tracks current section heading."""
    entries: list[dict] = []
    current_section = "General"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            # Heading
            current_section = stripped.lstrip("#").strip() or current_section
            continue
        # Look for bullet entries with markdown links
        if not (stripped.startswith("-") or stripped.startswith("*") or stripped.startswith("+")):
            continue
        m = _LINK_RE.search(stripped)
        if not m:
            continue
        name, url, desc = m.group(1), m.group(2), m.group(3).strip(" -:–")
        entries.append({
            "section": current_section,
            "name": name,
            "url": url,
            "description": desc,
        })
    return entries


def _search_osint(tool_input: dict, ctx: ToolContext) -> ToolResult:
    query = (tool_input.get("query") or "").strip()
    section_filter = (tool_input.get("section") or "").strip().lower()
    if not query and not section_filter:
        return ToolResult("query or section is required", is_error=True)

    readme = _find_readme(ctx.workspace)
    if readme is None:
        return ToolResult(
            "[FAIL] OSINT README not found in workspace or parent directories. "
            "Run EVA from inside the Awesome-OSINT-For-Everything repo.",
            is_error=True,
        )
    text = readme.read_text(errors="replace")
    entries = _parse_section(text)
    if not entries:
        return ToolResult("[FAIL] could not parse any tool entries from README.", is_error=True)

    q = query.lower()
    hits = []
    for e in entries:
        if section_filter and section_filter not in e["section"].lower():
            continue
        if query and not (
            q in e["name"].lower()
            or q in e["description"].lower()
            or q in e["section"].lower()
        ):
            continue
        hits.append(e)
        if len(hits) >= MAX_HITS:
            break

    if not hits:
        return ToolResult(f"[OK] no OSINT tools matched query={query!r} section={section_filter!r}")

    lines = [f"[OK] {len(hits)} match(es) from {readme.name}:"]
    for h in hits:
        desc = f" — {h['description']}" if h["description"] else ""
        lines.append(f"· [{h['section']}] {h['name']}: {h['url']}{desc}")
    return ToolResult("\n".join(lines))


def _list_osint_sections(tool_input: dict, ctx: ToolContext) -> ToolResult:
    readme = _find_readme(ctx.workspace)
    if readme is None:
        return ToolResult("[FAIL] OSINT README not found.", is_error=True)
    sections = []
    for line in readme.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("##") and not s.startswith("###"):
            sections.append(s.lstrip("#").strip())
    if not sections:
        return ToolResult("[FAIL] no top-level sections found.", is_error=True)
    return ToolResult(f"[OK] {len(sections)} sections:\n" + "\n".join(f"· {s}" for s in sections))


TOOLS: list[Tool] = [
    Tool(
        name="osint_search",
        description=(
            "Search the curated Awesome-OSINT-For-Everything corpus on this workstation "
            "for tools matching a query (e.g. 'username', 'email', 'reverse image', 'breach') "
            "or filtered by a section heading. Use this when the operator asks for OSINT "
            "recommendations on a target or technique. Returns tool name + URL + section."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text query."},
                "section": {"type": "string", "description": "Optional section heading filter (substring match)."},
            },
        },
        run=_search_osint,
        tags=["osint", "readonly"],
    ),
    Tool(
        name="osint_sections",
        description="List the top-level section headings of the OSINT corpus on this workstation.",
        input_schema={"type": "object", "properties": {}},
        run=_list_osint_sections,
        tags=["osint", "readonly"],
    ),
]
