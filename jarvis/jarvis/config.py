from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_EFFORT = "xhigh"
DEFAULT_VOICE = "Ava"
DEFAULT_RATE = 210
DEFAULT_USER_NAME = "Commander"


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Config:
    api_key: str
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    voice: str = DEFAULT_VOICE
    speak_rate: int = DEFAULT_RATE
    speak_by_default: bool = False
    user_name: str = DEFAULT_USER_NAME
    home_dir: Path = field(default_factory=lambda: Path.home() / ".jarvis")
    is_macos: bool = field(default_factory=lambda: platform.system() == "Darwin")
    workspace: Path = field(default_factory=Path.cwd)

    @property
    def memory_file(self) -> Path:
        return self.home_dir / "memory.json"

    @property
    def history_file(self) -> Path:
        return self.home_dir / "history"

    @property
    def log_file(self) -> Path:
        return self.home_dir / "session.log"

    def ensure_home(self) -> None:
        self.home_dir.mkdir(parents=True, exist_ok=True)


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_config() -> Config:
    # Pick up a .env from cwd or alongside the jarvis package
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        _load_dotenv(candidate)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Add it to your environment or a .env file."
        )

    home = Path(os.environ.get("JARVIS_HOME", "~/.jarvis")).expanduser()

    return Config(
        api_key=api_key,
        model=os.environ.get("JARVIS_MODEL", DEFAULT_MODEL),
        effort=os.environ.get("JARVIS_EFFORT", DEFAULT_EFFORT),
        voice=os.environ.get("JARVIS_VOICE", DEFAULT_VOICE),
        speak_rate=int(os.environ.get("JARVIS_SPEAK_RATE", DEFAULT_RATE)),
        speak_by_default=_env_bool("JARVIS_SPEAK", False),
        user_name=os.environ.get("JARVIS_USER_NAME", DEFAULT_USER_NAME),
        home_dir=home,
    )


def write_user_preferences(cfg: Config, prefs: dict) -> None:
    cfg.ensure_home()
    path = cfg.home_dir / "preferences.json"
    path.write_text(json.dumps(prefs, indent=2))


def read_user_preferences(cfg: Config) -> dict:
    path = cfg.home_dir / "preferences.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
