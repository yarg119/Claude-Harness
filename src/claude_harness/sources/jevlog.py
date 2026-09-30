"""Tail Jev decision rows (~/.claude/harness/jev/<sid>.jsonl)."""
from __future__ import annotations

from .. import paths
from .events import JsonlTail


class JevTail(JsonlTail):
    def __init__(self, session_id: str):
        super().__init__(paths.jev_file(session_id))
