"""Persistent JSON memory for EVA. Survives across sessions."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class MemoryEntry:
    key: str
    value: str
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        return cls(
            key=d["key"],
            value=d["value"],
            tags=d.get("tags", []),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


class MemoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, MemoryEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for d in data.get("entries", []):
            entry = MemoryEntry.from_dict(d)
            self.entries[entry.key] = entry

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        payload = {"entries": [e.to_dict() for e in self.entries.values()]}
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.path)

    def remember(self, key: str, value: str, tags: Iterable[str] = ()) -> MemoryEntry:
        now = time.time()
        if key in self.entries:
            e = self.entries[key]
            e.value = value
            e.tags = sorted(set(list(e.tags) + list(tags)))
            e.updated_at = now
        else:
            e = MemoryEntry(key=key, value=value, tags=sorted(set(tags)))
            self.entries[key] = e
        self._save()
        return e

    def recall(self, query: str | None = None, tag: str | None = None) -> list[MemoryEntry]:
        results = list(self.entries.values())
        if tag:
            results = [e for e in results if tag in e.tags]
        if query:
            q = query.lower()
            results = [
                e for e in results
                if q in e.key.lower() or q in e.value.lower() or any(q in t.lower() for t in e.tags)
            ]
        return sorted(results, key=lambda e: e.updated_at, reverse=True)

    def forget(self, key: str) -> bool:
        if key in self.entries:
            del self.entries[key]
            self._save()
            return True
        return False

    def summary(self, limit: int = 40) -> str:
        """Compact human-readable digest for the system prompt."""
        if not self.entries:
            return ""
        # Sort by most-recently-updated, take top N
        items = sorted(self.entries.values(), key=lambda e: e.updated_at, reverse=True)[:limit]
        lines = []
        for e in items:
            tagstr = f" [{', '.join(e.tags)}]" if e.tags else ""
            lines.append(f"- {e.key}: {e.value}{tagstr}")
        return "\n".join(lines)
