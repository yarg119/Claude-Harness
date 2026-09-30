"""Deep merge for settings files: objects merge, arrays union by value, fragment scalars win."""
from __future__ import annotations

import json
from typing import Any


def deep_merge(base: Any, add: Any) -> Any:
    if isinstance(base, dict) and isinstance(add, dict):
        out = dict(base)
        for k, v in add.items():
            out[k] = deep_merge(base.get(k), v) if k in base else v
        return out
    if isinstance(base, list) and isinstance(add, list):
        out = list(base)
        for item in add:
            if not any(_eq(item, x) for x in out):
                out.append(item)
        return out
    return base if add is None else add


def _eq(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def drop_hook_groups(settings: dict[str, Any], needle: str) -> dict[str, Any]:
    """Remove hook groups whose command contains `needle` (e.g. 'puppetmaster' or our hooks dir)."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings
    cleaned: dict[str, Any] = {}
    for event, groups in hooks.items():
        kept = []
        for g in groups or []:
            cmds = [h.get("command", "") for h in g.get("hooks", []) if isinstance(h, dict)]
            if any(needle in c for c in cmds):
                continue
            kept.append(g)
        if kept:
            cleaned[event] = kept
    out = dict(settings)
    if cleaned:
        out["hooks"] = cleaned
    else:
        out.pop("hooks", None)
    return out
