"""Local shell command execution. Gated by operator confirmation for destructive ops."""
from __future__ import annotations

import shlex
import subprocess

from .base import Tool, ToolContext, ToolResult

# Heuristic: commands containing any of these tokens require explicit confirmation.
DESTRUCTIVE_TOKENS = (
    "rm ", "rmdir", "mv ", "dd ", "mkfs", "shutdown", "reboot", "killall",
    " sudo", "sudo ", "chmod -R", "chown -R", ">", ">>", "git push", "git reset --hard",
    "git clean", "npm publish", "pip install", "brew install", "brew uninstall",
    "curl -X POST", "curl -X DELETE", "curl -X PUT", "wget ",
    "format ", "diskutil erase",
)

MAX_OUTPUT = 100_000


def _looks_destructive(cmd: str) -> bool:
    lower = cmd.lower()
    return any(tok in lower for tok in DESTRUCTIVE_TOKENS)


def _shell_exec(tool_input: dict, ctx: ToolContext) -> ToolResult:
    command = tool_input.get("command", "").strip()
    if not command:
        return ToolResult("command is required", is_error=True)
    timeout = int(tool_input.get("timeout", 60))
    force_confirm = bool(tool_input.get("confirm", False))
    cwd = tool_input.get("cwd")
    workdir = ctx.workspace
    if cwd:
        from pathlib import Path
        p = Path(cwd).expanduser()
        if not p.is_absolute():
            p = ctx.workspace / p
        workdir = p.resolve()

    if force_confirm or _looks_destructive(command):
        detail = f"$ {command}\ncwd={workdir}\ntimeout={timeout}s"
        if not ctx.confirm_destructive("shell_exec", detail):
            return ToolResult("[FAIL] operator declined shell_exec.", is_error=True)

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(f"[FAIL] command timed out after {timeout}s", is_error=True)
    except FileNotFoundError as e:
        return ToolResult(f"[FAIL] {e}", is_error=True)

    stdout = (proc.stdout or "")[:MAX_OUTPUT]
    stderr = (proc.stderr or "")[:MAX_OUTPUT]
    truncated = ""
    if proc.stdout and len(proc.stdout) > MAX_OUTPUT:
        truncated += f"\n[stdout truncated to {MAX_OUTPUT} bytes]"
    if proc.stderr and len(proc.stderr) > MAX_OUTPUT:
        truncated += f"\n[stderr truncated to {MAX_OUTPUT} bytes]"
    status = "OK" if proc.returncode == 0 else f"FAIL exit={proc.returncode}"
    body = f"[{status}] cwd={workdir}\n$ {command}\n"
    if stdout:
        body += f"--- stdout ---\n{stdout}\n"
    if stderr:
        body += f"--- stderr ---\n{stderr}\n"
    body += truncated
    return ToolResult(body, is_error=proc.returncode != 0)


TOOLS: list[Tool] = [
    Tool(
        name="shell_exec",
        description=(
            "Execute a shell command on the operator's local machine. "
            "Read-only / informational commands (ls, cat, git status, ps, ifconfig, etc.) run immediately. "
            "Commands that look destructive (rm, mv, sudo, redirection, git push, package installs, etc.) "
            "trigger an operator confirmation prompt. Pass confirm=true to force the prompt even for safe-looking commands."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run (sh/bash semantics)."},
                "cwd": {"type": "string", "description": "Optional working directory."},
                "timeout": {"type": "integer", "default": 60, "description": "Seconds before the command is killed."},
                "confirm": {"type": "boolean", "default": False, "description": "Force the confirmation prompt."},
            },
            "required": ["command"],
        },
        run=_shell_exec,
        tags=["shell"],
    ),
]
