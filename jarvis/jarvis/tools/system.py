"""System telemetry — time, OS, network, disk, battery. macOS-aware."""
from __future__ import annotations

import datetime as _dt
import platform
import shutil
import socket
import subprocess
import sys

from .base import Tool, ToolContext, ToolResult


def _now(tool_input: dict, ctx: ToolContext) -> ToolResult:
    tz = tool_input.get("timezone")
    if tz:
        # Stay dependency-free: report local + UTC + the requested zone via `date` if available
        try:
            out = subprocess.run(
                ["date"],
                env={"TZ": tz, "PATH": "/usr/bin:/bin"},
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if out.returncode == 0:
                return ToolResult(out.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    now = _dt.datetime.now().astimezone()
    return ToolResult(
        f"local: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"utc:   {_dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"epoch: {int(now.timestamp())}"
    )


def _system_info(tool_input: dict, ctx: ToolContext) -> ToolResult:
    info = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "hostname": socket.gethostname(),
        "user": _safe_run(["whoami"]),
        "cwd": str(ctx.workspace),
    }
    if sys.platform == "darwin":
        info["macos_version"] = _safe_run(["sw_vers", "-productVersion"])
        info["uptime"] = _safe_run(["uptime"])
        info["battery"] = _macos_battery()
    return ToolResult("\n".join(f"{k}: {v}" for k, v in info.items()))


def _safe_run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
        return (out.stdout or out.stderr).strip() or "?"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "?"


def _macos_battery() -> str:
    if not shutil.which("pmset"):
        return "n/a"
    out = _safe_run(["pmset", "-g", "batt"])
    # pmset returns multi-line text; keep the meaningful line
    for line in out.splitlines():
        if "%" in line:
            return line.strip().strip(";")
    return out.splitlines()[0] if out else "n/a"


def _disk(tool_input: dict, ctx: ToolContext) -> ToolResult:
    out = _safe_run(["df", "-h"])
    return ToolResult(out)


def _network(tool_input: dict, ctx: ToolContext) -> ToolResult:
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except OSError:
        local_ip = "?"
    parts = [f"hostname: {hostname}", f"local_ip: {local_ip}"]
    if shutil.which("ifconfig"):
        parts.append("\n" + _safe_run(["ifconfig"]))
    elif shutil.which("ip"):
        parts.append("\n" + _safe_run(["ip", "addr"]))
    return ToolResult("\n".join(parts))


TOOLS: list[Tool] = [
    Tool(
        name="get_time",
        description="Report current local time, UTC, and Unix epoch. Optional 'timezone' (IANA, e.g. 'Europe/London').",
        input_schema={
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "IANA timezone name."},
            },
        },
        run=_now,
        tags=["system", "readonly"],
    ),
    Tool(
        name="system_info",
        description="Report OS, hostname, user, working directory, and (on macOS) version, uptime, and battery state.",
        input_schema={"type": "object", "properties": {}},
        run=_system_info,
        tags=["system", "readonly"],
    ),
    Tool(
        name="disk_usage",
        description="Show local disk usage via `df -h`.",
        input_schema={"type": "object", "properties": {}},
        run=_disk,
        tags=["system", "readonly"],
    ),
    Tool(
        name="network_info",
        description="Show hostname, local IP, and active network interfaces.",
        input_schema={"type": "object", "properties": {}},
        run=_network,
        tags=["system", "readonly"],
    ),
]
