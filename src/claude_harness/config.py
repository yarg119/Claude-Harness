"""Harness toggles stored in ~/.claude/harness/config.json (read by hooks via jq)."""
from __future__ import annotations

import json
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "codex": False,
    "jev": False,
    "jev_threshold": 0.80,
    "layout": "auto",
    "one_million_context": False,
}


def load() -> dict[str, Any]:
    try:
        data = json.loads(paths.CONFIG.read_text())
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **data}


def save(cfg: dict[str, Any]) -> None:
    paths.ensure_dirs()
    paths.CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")


def set_value(key: str, value: Any) -> dict[str, Any]:
    cfg = load()
    cfg[key] = value
    save(cfg)
    return cfg
