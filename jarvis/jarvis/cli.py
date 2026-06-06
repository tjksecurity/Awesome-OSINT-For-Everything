"""EVA CLI — the operator-facing terminal."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from .agent import Agent
from .config import load_config
from .memory import MemoryStore
from .voice import VoiceEngine

BANNER = r"""
   ______ _    __ ___
  |  ____| |  / //   |
  | |__  | | / // /| |
  |  __| | |/ // /_| |
  | |____|   // ___  |
  |______|__//_/   |_|
  Electronic Video Agent — Red Alert protocol active
"""


def _print_banner(console: Console, voice_status: str, model: str, effort: str) -> None:
    text = Text(BANNER, style="bold green")
    console.print(text)
    console.print(
        f"[dim]model:[/] {model}   "
        f"[dim]effort:[/] {effort}   "
        f"[dim]{voice_status}[/]",
        highlight=False,
    )
    console.print(
        "[dim]commands:[/] /help /voice /memory /reset /quit   "
        "[dim](Ctrl-C interrupts, Ctrl-D quits)[/]",
        highlight=False,
    )
    console.print()


def _print_help(console: Console) -> None:
    console.print(
        Panel.fit(
            "[bold]Slash commands[/]\n"
            "[cyan]/help[/]     show this help\n"
            "[cyan]/voice[/]    toggle TTS (macOS only)\n"
            "[cyan]/memory[/]   dump persistent memory\n"
            "[cyan]/forget[/] [i]KEY[/]   delete a memory entry\n"
            "[cyan]/reset[/]    clear conversation history (keeps memory)\n"
            "[cyan]/cwd[/] [i]PATH[/]   change EVA's working directory\n"
            "[cyan]/model[/] [i]ID[/]   switch Claude model for this session\n"
            "[cyan]/effort[/] [i]LEVEL[/]   low|medium|high|xhigh|max\n"
            "[cyan]/quit[/]     exit\n\n"
            "[dim]Anything else is sent to EVA.[/]",
            title="EVA help",
            border_style="green",
        )
    )


def _confirm_factory(console: Console):
    """Build the destructive-action confirmation prompt."""

    def confirm(action: str, detail: str) -> bool:
        console.print()
        console.print(
            Panel(
                f"[yellow]EVA requests authorization to execute:[/]\n[bold]{action}[/]\n\n{detail}",
                title="[red]CONFIRM[/]",
                border_style="red",
            )
        )
        try:
            return Confirm.ask("Authorize?", default=False, console=console)
        except (KeyboardInterrupt, EOFError):
            return False

    return confirm


def _handle_slash(line: str, agent: Agent, voice: VoiceEngine, console: Console) -> bool:
    """Handle slash commands. Returns True if EVA should not be invoked."""
    parts = line.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        _print_help(console)
        return True
    if cmd == "/quit" or cmd == "/exit":
        console.print("[green]EVA:[/] Standing down. Connection terminated.")
        raise SystemExit(0)
    if cmd == "/voice":
        if not voice.available:
            console.print("[yellow]voice subsystem unavailable on this workstation.[/]")
            return True
        state = voice.toggle()
        console.print(f"[green]EVA:[/] {voice.status()}")
        if state:
            voice.speak(f"Voice channel open, {agent.config.user_name}.")
        return True
    if cmd == "/memory":
        summary = agent.memory.summary()
        if not summary:
            console.print("[dim]memory is empty.[/]")
        else:
            console.print(Panel(summary, title="memory", border_style="green"))
        return True
    if cmd == "/forget":
        if not arg:
            console.print("[yellow]usage: /forget KEY[/]")
        else:
            ok = agent.memory.forget(arg.strip())
            console.print(f"[green]EVA:[/] {'deleted ' + arg if ok else 'no such memory: ' + arg}")
        return True
    if cmd == "/reset":
        agent.reset()
        console.print("[green]EVA:[/] Tactical buffer cleared. Memory retained.")
        return True
    if cmd == "/cwd":
        if not arg:
            console.print(f"[dim]cwd: {agent.config.workspace}[/]")
        else:
            p = Path(arg).expanduser().resolve()
            if not p.exists() or not p.is_dir():
                console.print(f"[red]no such directory: {p}[/]")
            else:
                agent.config.workspace = p
                agent._ctx.workspace = p
                console.print(f"[green]EVA:[/] workspace reassigned: {p}")
        return True
    if cmd == "/model":
        if not arg:
            console.print(f"[dim]model: {agent.config.model}[/]")
        else:
            agent.config.model = arg.strip()
            console.print(f"[green]EVA:[/] model reassigned: {agent.config.model}")
        return True
    if cmd == "/effort":
        if not arg:
            console.print(f"[dim]effort: {agent.config.effort}[/]")
        else:
            agent.config.effort = arg.strip()
            console.print(f"[green]EVA:[/] effort level: {agent.config.effort}")
        return True
    console.print(f"[yellow]unknown command: {cmd}[/]  (try /help)")
    return True


def _render_turn(agent: Agent, voice: VoiceEngine, console: Console, user_input: str) -> None:
    """Run one user turn, streaming output to the console and the voice engine."""
    pending_speech: list[str] = []
    text_buffer = ""
    speech_flush_chars = ".!?\n"

    console.print("[bold green]EVA[/] [dim]›[/] ", end="")
    try:
        for ev in agent.turn(user_input):
            if ev.kind == "text":
                console.print(ev.text, end="", style="green", highlight=False)
                text_buffer += ev.text
                # Speak in natural chunks so EVA doesn't wait until the whole reply ends.
                if voice.enabled and voice.available and any(c in ev.text for c in speech_flush_chars):
                    pending_speech.append(text_buffer)
                    text_buffer = ""
            elif ev.kind == "tool_use_start":
                console.print(f"\n[dim cyan]· deploying {ev.tool_name}…[/]", highlight=False)
            elif ev.kind == "thinking":
                # Adaptive thinking is omitted by default; if surfaced, dim it.
                pass
            elif ev.kind == "error":
                style = "red" if ev.is_error else "yellow"
                console.print(f"\n[{style}]{ev.text}[/]")
            elif ev.kind == "turn_end":
                break
    except KeyboardInterrupt:
        voice.stop()
        console.print("\n[yellow][interrupted by operator][/]")
        return

    console.print()  # newline after final stream
    if text_buffer:
        pending_speech.append(text_buffer)
    if voice.enabled and voice.available:
        full = " ".join(p.strip() for p in pending_speech if p.strip())
        if full:
            voice.speak(full, blocking=False)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarvis", description="EVA — your personal AI commander.")
    p.add_argument("--voice", action="store_true", help="enable TTS at startup (macOS only)")
    p.add_argument("--no-voice", action="store_true", help="disable TTS at startup")
    p.add_argument("--model", help="override model ID")
    p.add_argument("--effort", help="override effort level")
    p.add_argument("--cwd", help="set EVA's working directory")
    p.add_argument("prompt", nargs="*", help="optional one-shot prompt; if given, EVA answers once and exits")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()

    try:
        cfg = load_config()
    except SystemExit as e:
        console.print(f"[red]{e}[/]")
        return 1

    if args.model:
        cfg.model = args.model
    if args.effort:
        cfg.effort = args.effort
    if args.cwd:
        p = Path(args.cwd).expanduser().resolve()
        if not p.is_dir():
            console.print(f"[red]not a directory: {p}[/]")
            return 1
        cfg.workspace = p

    cfg.ensure_home()
    memory = MemoryStore(cfg.memory_file)

    voice_enabled = cfg.speak_by_default
    if args.voice:
        voice_enabled = True
    if args.no_voice:
        voice_enabled = False
    voice = VoiceEngine(voice=cfg.voice, rate=cfg.speak_rate, enabled=voice_enabled and not args.no_voice)
    # Attach to config so tools (e.g. `speak`) can reach the engine via ctx.
    cfg._voice_engine = voice  # type: ignore[attr-defined]

    confirm = _confirm_factory(console)
    agent = Agent(config=cfg, memory=memory, confirm_destructive=confirm)

    # One-shot mode
    if args.prompt:
        prompt = " ".join(args.prompt)
        _render_turn(agent, voice, console, prompt)
        return 0

    _print_banner(console, voice.status(), cfg.model, cfg.effort)
    if voice.enabled and voice.available:
        voice.speak(f"EVA online. Standing by, {cfg.user_name}.")

    history_file = cfg.history_file
    history_file.parent.mkdir(parents=True, exist_ok=True)
    session: PromptSession = PromptSession(history=FileHistory(str(history_file)))

    while True:
        try:
            with patch_stdout():
                line = session.prompt(f"\n{cfg.user_name} › ")
        except KeyboardInterrupt:
            console.print("[dim](Ctrl-D or /quit to exit)[/]")
            continue
        except EOFError:
            console.print("\n[green]EVA:[/] Standing down. Connection terminated.")
            return 0

        line = line.strip()
        if not line:
            continue
        if line.startswith("/"):
            _handle_slash(line, agent, voice, console)
            continue

        _render_turn(agent, voice, console, line)


if __name__ == "__main__":
    sys.exit(main())
