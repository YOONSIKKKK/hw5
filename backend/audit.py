"""Append-only execution log for the agent team.

Writes to ``output/audit_trail.json`` as a growing JSON array.  The file is
never truncated: every run appends to whatever is already there, so the trail
spans the whole history of the project rather than just the last execution.
"""

from __future__ import annotations

import json
import os
import threading
from itertools import count
from pathlib import Path
from typing import Any, Callable

from backend.config import AUDIT_TRAIL, OUTPUT_DIR
from backend.models import AuditEvent


def _truncate(value: Any, limit: int = 2_000) -> Any:
    """Keep the trail readable -- long tool payloads are clipped, not dropped."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"... [truncated {len(value) - limit} chars]"
    if isinstance(value, dict):
        return {k: _truncate(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 40:
            return [_truncate(v, limit) for v in value[:40]] + [
                f"... [truncated {len(value) - 40} more items]"
            ]
        return [_truncate(v, limit) for v in value]
    return value


class AuditTrail:
    """Thread-safe appender for ``output/audit_trail.json``."""

    def __init__(self, run_id: str, path: Path | None = None) -> None:
        self.run_id = run_id
        self.path = path or AUDIT_TRAIL
        self._lock = threading.Lock()
        self._seq = count(1)
        self._subscribers: list[Callable[[AuditEvent], None]] = []
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self._events: list[dict[str, Any]] = self._load_existing()

    def _load_existing(self) -> list[dict[str, Any]]:
        """Read whatever is already on disk so this run appends to it."""
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Never destroy an unreadable trail -- move it aside and start fresh.
            backup = self.path.with_suffix(".corrupt.json")
            self.path.replace(backup)
            return []
        return data if isinstance(data, list) else []

    def subscribe(self, callback: Callable[[AuditEvent], None]) -> None:
        """Register a listener (the dashboard's live event stream uses this)."""
        self._subscribers.append(callback)

    def record(self, **fields: Any) -> AuditEvent:
        """Append one event to the trail and flush it to disk immediately."""
        with self._lock:
            event = AuditEvent(run_id=self.run_id, seq=next(self._seq), **fields)
            payload = event.model_dump(exclude_none=True)
            payload = _truncate(payload)
            self._events.append(payload)
            self._flush()
        for callback in self._subscribers:
            try:
                callback(event)
            except Exception:  # a broken listener must not break the run
                pass
        return event

    def _flush(self) -> None:
        """Atomic rewrite so a crash mid-write cannot corrupt the trail."""
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._events, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def run_events(self) -> list[dict[str, Any]]:
        return [e for e in self._events if e.get("run_id") == self.run_id]
