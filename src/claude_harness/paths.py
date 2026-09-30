"""Filesystem locations used by the harness (repo side and installed side)."""
from __future__ import annotations

import os
from pathlib import Path

HOME = Path(os.environ.get("HARNESS_TEST_HOME", Path.home()))
CLAUDE_DIR = HOME / ".claude"
CODEX_DIR = HOME / ".codex"
HARNESS_HOME = Path(os.environ.get("HARNESS_HOME", CLAUDE_DIR / "harness"))
SETTINGS = CLAUDE_DIR / "settings.json"
CLAUDE_JSON = HOME / ".claude.json"
CONFIG = HARNESS_HOME / "config.json"

REPO = Path(__file__).resolve().parents[2]
REPO_CLAUDE = REPO / "claude"
REPO_CODEX = REPO / "codex"
REPO_TEMPLATE = REPO / "templates" / "project"

for _d in ("events", "sessions", "status", "state", "jev", "backups"):
    pass  # created lazily by ensure_dirs()


def ensure_dirs() -> None:
    for d in ("events", "sessions", "status", "state", "jev", "backups"):
        (HARNESS_HOME / d).mkdir(parents=True, exist_ok=True)


def events_file(session_id: str) -> Path:
    return HARNESS_HOME / "events" / f"{session_id}.jsonl"


def session_file(session_id: str) -> Path:
    return HARNESS_HOME / "sessions" / f"{session_id}.json"


def status_file(session_id: str) -> Path:
    return HARNESS_HOME / "status" / f"{session_id}.json"


def jev_file(session_id: str) -> Path:
    return HARNESS_HOME / "jev" / f"{session_id}.jsonl"


def state_dir(session_id: str) -> Path:
    return HARNESS_HOME / "state" / session_id
