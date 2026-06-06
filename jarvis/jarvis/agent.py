"""EVA's brain — Claude API client with streaming, tool use, and prompt caching."""
from __future__ import annotations

import json
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import anthropic

from .config import Config
from .memory import MemoryStore
from .persona import build_system_prompt
from . import tools as tool_pkg
from .tools.base import ToolContext


# Anthropic server-side tool versions — see claude-api skill for current strings.
SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
    {"type": "code_execution_20260120", "name": "code_execution"},
]


@dataclass
class StreamEvent:
    kind: str  # text | thinking | tool_use_start | tool_result | turn_end | error
    text: str = ""
    tool_name: str = ""
    is_error: bool = False


@dataclass
class Agent:
    config: Config
    memory: MemoryStore
    confirm_destructive: Callable[[str, str], bool]
    exclude_tool_tags: tuple[str, ...] = ()
    client: anthropic.Anthropic = field(init=False)
    messages: list[dict] = field(default_factory=list)
    system_prompt: str = field(default="", init=False)
    _tool_schemas: list[dict] = field(default_factory=list, init=False)
    _ctx: ToolContext = field(init=False)

    def __post_init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=self.config.api_key)
        workstation = f"{platform.system()} {platform.release()} ({platform.machine()})"
        self.system_prompt = build_system_prompt(
            user_name=self.config.user_name,
            workspace=self.config.workspace,
            workstation=workstation,
            memory_summary=self.memory.summary(),
        )
        # Cached tool list = custom tools (filtered) + Anthropic server-side tools
        custom = tool_pkg.schemas_for_api(exclude_tags=self.exclude_tool_tags)
        self._tool_schemas = custom + SERVER_TOOLS
        self._ctx = ToolContext(
            config=self.config,
            memory=self.memory,
            workspace=self.config.workspace,
            confirm_destructive=self.confirm_destructive,
        )

    # ---------- public API ----------

    def reset(self) -> None:
        self.messages = []
        # Refresh system prompt with latest memory snapshot
        workstation = f"{platform.system()} {platform.release()} ({platform.machine()})"
        self.system_prompt = build_system_prompt(
            user_name=self.config.user_name,
            workspace=self.config.workspace,
            workstation=workstation,
            memory_summary=self.memory.summary(),
        )

    def turn(self, user_input: str) -> Iterator[StreamEvent]:
        """Run one user turn end-to-end. Yields stream events for the CLI to render."""
        self.messages.append({"role": "user", "content": user_input})
        yield from self._agentic_loop()

    # ---------- internals ----------

    def _make_request(self) -> anthropic.MessageStreamManager:
        """Build the streaming request, with cache_control on the last system block and tools."""
        # System prompt as a single cached block.
        system_blocks = [
            {
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        # Tools — cache the last one to lock in the tool prefix. The list is
        # rendered deterministically because we build it once at construction.
        tools = [dict(t) for t in self._tool_schemas]
        if tools:
            tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}

        return self.client.messages.stream(
            model=self.config.model,
            max_tokens=64000,
            system=system_blocks,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": self.config.effort},
            messages=self.messages,
        )

    def _agentic_loop(self) -> Iterator[StreamEvent]:
        """Manual tool-use loop with streaming. Yields events to the renderer."""
        max_iterations = 25
        for _ in range(max_iterations):
            try:
                with self._make_request() as stream:
                    current_text_block_active = False
                    for event in stream:
                        etype = event.type
                        if etype == "content_block_start":
                            block = event.content_block
                            if block.type == "text":
                                current_text_block_active = True
                            elif block.type == "tool_use":
                                yield StreamEvent(kind="tool_use_start", tool_name=block.name)
                            elif block.type == "server_tool_use":
                                yield StreamEvent(kind="tool_use_start", tool_name=block.name)
                        elif etype == "content_block_delta":
                            delta = event.delta
                            if delta.type == "text_delta":
                                yield StreamEvent(kind="text", text=delta.text)
                            elif delta.type == "thinking_delta":
                                # Thinking is omitted by default on Opus 4.7 — left here in case
                                # the user enables display=summarized later.
                                yield StreamEvent(kind="thinking", text=delta.thinking)
                        elif etype == "content_block_stop":
                            current_text_block_active = False
                    final = stream.get_final_message()
            except anthropic.APIStatusError as e:
                yield StreamEvent(kind="error", text=f"API {e.status_code}: {e.message}", is_error=True)
                return
            except anthropic.APIError as e:
                yield StreamEvent(kind="error", text=f"API error: {e}", is_error=True)
                return

            # Persist assistant turn (with full content, including tool_use blocks).
            self.messages.append({"role": "assistant", "content": final.content})

            if final.stop_reason == "end_turn":
                yield StreamEvent(kind="turn_end")
                return
            if final.stop_reason == "max_tokens":
                yield StreamEvent(
                    kind="error",
                    text="[WARN] response truncated at max_tokens — ask EVA to continue.",
                )
                yield StreamEvent(kind="turn_end")
                return
            if final.stop_reason == "refusal":
                yield StreamEvent(kind="error", text="[FAIL] EVA refused this request.", is_error=True)
                yield StreamEvent(kind="turn_end")
                return
            if final.stop_reason == "pause_turn":
                # Server-side tool hit iteration cap — re-send to resume.
                continue
            if final.stop_reason == "tool_use":
                tool_results = self._execute_pending_tools(final.content)
                if tool_results:
                    self.messages.append({"role": "user", "content": tool_results})
                # loop continues
                continue

            # Unknown stop reason — bail.
            yield StreamEvent(
                kind="error",
                text=f"[WARN] unexpected stop_reason={final.stop_reason}; ending turn.",
            )
            yield StreamEvent(kind="turn_end")
            return

        yield StreamEvent(
            kind="error",
            text=f"[WARN] tool-use loop exceeded {max_iterations} iterations; ending turn.",
        )
        yield StreamEvent(kind="turn_end")

    def _execute_pending_tools(self, content: list) -> list[dict]:
        """Run every client-side tool_use block in the assistant's response."""
        results: list[dict] = []
        for block in content:
            btype = getattr(block, "type", None)
            if btype != "tool_use":
                # server_tool_use / server_tool_result are handled server-side; skip.
                continue
            name = block.name
            tool_input = block.input or {}
            res = tool_pkg.dispatch(name, tool_input, self._ctx)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": res.content,
                "is_error": res.is_error,
            })
        return results
