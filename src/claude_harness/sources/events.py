"""Tail the hook event stream (~/.claude/harness/events/<sid>.jsonl) and session registry."""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .. import paths


def latest_session_id() -> str | None:
    d = paths.HARNESS_HOME / "sessions"
    if not d.exists():
        return None
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0].stem if files else None


def session_info(session_id: str) -> dict[str, Any]:
    try:
        return json.loads(paths.session_file(session_id).read_text())
    except (OSError, ValueError):
        return {"session_id": session_id}


class JsonlTail:
    """Incremental reader for an append-only JSONL file; tolerant of partial last lines."""

    def __init__(self, path: Path):
        self.path = path
        self.pos = 0
        self.buf = ""

    def read_new(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            size = self.path.stat().st_size
        except OSError:
            return out
        if size < self.pos:  # truncated / rotated
            self.pos, self.buf = 0, ""
        if size == self.pos:
            return out
        with self.path.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(self.pos)
            chunk = f.read()
            self.pos = f.tell()
        self.buf += chunk
        lines = self.buf.split("\n")
        self.buf = lines.pop()  # incomplete tail
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


def tail_events(session_id: str, follow: bool = False, poll: float = 0.25) -> Iterator[dict[str, Any]]:
    tail = JsonlTail(paths.events_file(session_id))
    while True:
        for ev in tail.read_new():
            yield ev
        if not follow:
            return
        time.sleep(poll)
