"""TTS via macOS `say`. EVA-style female voice.

On non-macOS, voice ops are no-ops with a notice. For richer voice synthesis
(ElevenLabs, etc.) drop in a new backend that conforms to the speak() signature.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


class VoiceEngine:
    def __init__(self, voice: str = "Ava", rate: int = 210, enabled: bool = False):
        self.voice = voice
        self.rate = rate
        self.enabled = enabled
        self._available = self._detect()
        self._current_proc: subprocess.Popen | None = None

    def _detect(self) -> bool:
        # macOS `say` is the cleanest path. Skip otherwise.
        if sys.platform != "darwin":
            return False
        return shutil.which("say") is not None

    @property
    def available(self) -> bool:
        return self._available

    def toggle(self) -> bool:
        if not self._available:
            return False
        self.enabled = not self.enabled
        return self.enabled

    def speak(self, text: str, blocking: bool = False) -> None:
        if not self.enabled or not self._available or not text.strip():
            return
        # Stop any prior utterance — EVA does not stutter.
        self.stop()
        # Strip markdown noise that sounds bad spoken.
        clean = _scrub_for_speech(text)
        if not clean.strip():
            return
        cmd = ["say", "-v", self.voice, "-r", str(self.rate), clean]
        try:
            if blocking:
                subprocess.run(cmd, check=False)
            else:
                # Detach so the CLI keeps streaming while EVA speaks.
                self._current_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
        except (OSError, FileNotFoundError):
            self._available = False

    def stop(self) -> None:
        if self._current_proc and self._current_proc.poll() is None:
            try:
                self._current_proc.terminate()
            except OSError:
                pass
        self._current_proc = None

    def status(self) -> str:
        if not self._available:
            return "voice: unavailable (requires macOS `say`)"
        return f"voice: {'ENABLED' if self.enabled else 'muted'} ({self.voice}, {self.rate} wpm)"


def _scrub_for_speech(text: str) -> str:
    """Remove characters that sound awful when read aloud."""
    drop = ("```", "`", "*", "_", "#", "[OK]", "[WARN]", "[FAIL]", "·")
    out = text
    for d in drop:
        out = out.replace(d, "")
    # Collapse whitespace
    return " ".join(out.split())
