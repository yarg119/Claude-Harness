"""Read the status-line mirror (~/.claude/harness/status/<sid>.json) and harness config."""
from __future__ import annotations

import json
from typing import Any

from .. import config, paths


def read_status(session_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(paths.status_file(session_id).read_text())
    except (OSError, ValueError):
        return None


def read_config() -> dict[str, Any]:
    return config.load()
