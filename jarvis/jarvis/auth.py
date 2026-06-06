"""Authorizer — stateful gate for destructive ops in server mode.

CLI mode uses an interactive prompt. Server mode uses this state machine: the
operator flips authorization on via /authorize, EVA gets one (or all) destructive
calls through, then the gate re-locks.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class AuthState:
    mode: str = "deny"  # "deny" | "one_shot" | "session"
    expires_at: float = 0.0  # 0 = no expiry; otherwise unix epoch


class Authorizer:
    """Thread-safe authorization gate."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = AuthState()
        self._last_check: tuple[str, str] | None = None

    def confirm(self, action: str, detail: str) -> bool:
        """Called by tools to check if the operation is allowed."""
        with self._lock:
            self._last_check = (action, detail)
            now = time.time()
            if self._state.mode == "deny":
                return False
            if self._state.expires_at and now > self._state.expires_at:
                self._state = AuthState()
                return False
            if self._state.mode == "one_shot":
                # Burn the grant.
                self._state = AuthState()
                return True
            if self._state.mode == "session":
                return True
            return False

    def set_mode(self, mode: str, ttl_seconds: int = 0) -> AuthState:
        if mode not in ("deny", "one_shot", "session"):
            raise ValueError(f"invalid mode: {mode}")
        with self._lock:
            expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else 0.0
            self._state = AuthState(mode=mode, expires_at=expires_at)
            return self._state

    @property
    def state(self) -> AuthState:
        with self._lock:
            return AuthState(mode=self._state.mode, expires_at=self._state.expires_at)

    @property
    def last_check(self) -> tuple[str, str] | None:
        return self._last_check
