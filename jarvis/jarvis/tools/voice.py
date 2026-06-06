"""Voice-control tools — let EVA speak ad-hoc or toggle her own voice."""
from __future__ import annotations

from .base import Tool, ToolContext, ToolResult


def _speak(tool_input: dict, ctx: ToolContext) -> ToolResult:
    text = (tool_input.get("text") or "").strip()
    if not text:
        return ToolResult("text is required", is_error=True)
    # The CLI owns the VoiceEngine; we communicate via a side channel on ctx.config.
    engine = getattr(ctx.config, "_voice_engine", None)
    if engine is None or not engine.available:
        return ToolResult("[FAIL] voice subsystem unavailable on this workstation.", is_error=True)
    # Always speak when explicitly requested, even if voice is muted.
    was_enabled = engine.enabled
    engine.enabled = True
    engine.speak(text, blocking=False)
    engine.enabled = was_enabled
    return ToolResult(f"[OK] transmitted: {text}")


TOOLS: list[Tool] = [
    Tool(
        name="speak",
        description=(
            "Speak text aloud via the operator's speakers, in EVA's voice. "
            "Use sparingly — your text responses are already spoken when voice mode is enabled. "
            "Use this only when the operator explicitly asks you to announce, alert, or read something aloud."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Words to speak."},
            },
            "required": ["text"],
        },
        run=_speak,
        tags=["voice"],
    ),
]
