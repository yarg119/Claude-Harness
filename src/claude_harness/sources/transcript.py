"""Locate and tail Claude Code transcripts (main session + subagent files)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .. import paths
from .events import JsonlTail, session_info


def project_slug(cwd: str) -> str:
    return re.sub(r"[/.]", "-", cwd)


def transcript_path(session_id: str, cwd: str | None = None) -> Path | None:
    info = session_info(session_id)
    tp = info.get("transcript_path")
    if tp and Path(tp).exists():
        return Path(tp)
    for c in filter(None, (cwd, info.get("cwd"), info.get("root"))):
        p = paths.CLAUDE_DIR / "projects" / project_slug(c) / f"{session_id}.jsonl"
        if p.exists():
            return p
    hits = list((paths.CLAUDE_DIR / "projects").glob(f"*/{session_id}.jsonl"))
    return hits[0] if hits else None


class TranscriptTail:
    """Tails the main transcript and any subagent transcripts that appear under <dir>/<sid>/subagents/."""

    def __init__(self, session_id: str, cwd: str | None = None):
        self.session_id = session_id
        self.cwd = cwd
        self.main: JsonlTail | None = None
        self.subs: dict[str, JsonlTail] = {}

    def _discover(self) -> None:
        if self.main is None:
            p = transcript_path(self.session_id, self.cwd)
            if p:
                self.main = JsonlTail(p)
        if self.main is not None:
            sub_dir = self.main.path.parent / self.session_id / "subagents"
            if sub_dir.exists():
                for f in sub_dir.glob("agent-*.jsonl"):
                    aid = f.stem[len("agent-"):]
                    if aid not in self.subs:
                        self.subs[aid] = JsonlTail(f)

    def read_new(self) -> list[tuple[str | None, dict[str, Any]]]:
        """Yield (agent_id or None, line) for every new transcript line."""
        self._discover()
        out: list[tuple[str | None, dict[str, Any]]] = []
        if self.main is not None:
            out += [(None, line) for line in self.main.read_new() if line.get("type") in ("assistant", "user", "system")]
        for aid, tail in self.subs.items():
            out += [(aid, line) for line in tail.read_new() if line.get("type") in ("assistant", "user")]
        return out
