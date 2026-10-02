"""Vendored third-party skills: pinned copies in claude/skills/ (Claude Code) and codex/skills/ (Codex).

`harness skills` lists them; `harness skills update [name] [--ref REF]` re-fetches from the manifest,
rewrites SKILL.md + SOURCE.md and prints a diff stat so the change can be reviewed before committing."""
from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import paths

MANIFEST = paths.REPO / "vendor" / "skills.json"

WIG_FRONTMATTER = """---
name: web-interface-guidelines
description: Audit UI code against Vercel's Web Interface Guidelines (accessibility, focus states, forms, animation, typography, content handling, images, performance, navigation, touch, dark mode, i18n). Use when reviewing changed UI files, before declaring UI work done, or when asked to check accessibility, UX or interface quality. Read-only; reports file:line findings.
argument-hint: <file-or-pattern>
---
"""


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text())["skills"]


def skill_dir(entry: dict) -> Path:
    base = paths.REPO_CLAUDE if entry["target"] == "claude" else paths.REPO_CODEX
    return base / "skills" / entry["name"]


def transform(entry: dict, text: str) -> str:
    if entry.get("transform") == "command-to-skill":
        body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)   # drop the command frontmatter
        return WIG_FRONTMATTER + "\n" + body.lstrip("\n")
    return text


def source_note(entry: dict, ref: str) -> str:
    return (f"# Source\n\n- Upstream: {entry['repo']} (`{entry['path']}`)\n- Pinned commit: `{ref}`\n"
            f"- License: {entry['license']}\n- Homepage: {entry.get('homepage', entry['repo'])}\n"
            f"- Vendored: {_dt.date.today().isoformat()} by `harness skills update`\n"
            + ("- Local change: Claude Code command frontmatter replaced with skill frontmatter; rules unchanged.\n"
               if entry.get("transform") == "command-to-skill" else "- Local change: none.\n")
            + "\nThis file is not loaded by the agent. Project rules (e.g. Verax `docs/agents/ui.md`) decide when and how "
              "this skill applies and override its styling choices.\n")


def update(name: str | None = None, ref: str | None = None) -> list[str]:
    log: list[str] = []
    entries = [e for e in load_manifest() if name in (None, e["name"])]
    if not entries:
        return [f"no vendored skill named {name!r}"]
    manifest = json.loads(MANIFEST.read_text())
    with tempfile.TemporaryDirectory() as tmp:
        clones: dict[str, Path] = {}
        for e in entries:
            want = ref or e["ref"]
            key = f"{e['repo']}@{want}"
            if key not in clones:
                d = Path(tmp) / str(len(clones))
                subprocess.run(["git", "clone", "-q", e["repo"], str(d)], check=True)
                subprocess.run(["git", "-C", str(d), "checkout", "-q", want], check=True)
                clones[key] = d
            d = clones[key]
            sha = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            out = skill_dir(e)
            out.mkdir(parents=True, exist_ok=True)
            (out / "SKILL.md").write_text(transform(e, (d / e["path"]).read_text()))
            (out / "SOURCE.md").write_text(source_note(e, sha))
            for m in manifest["skills"]:
                if m["name"] == e["name"]:
                    m["ref"] = sha
            log.append(f"{e['name']}: {sha[:10]} -> {out.relative_to(paths.REPO)}")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    stat = subprocess.run(["git", "-C", str(paths.REPO), "diff", "--stat", "--", "claude/skills", "codex/skills", "vendor"],
                          capture_output=True, text=True).stdout.strip()
    log.append(stat or "no changes")
    return log


def listing() -> list[str]:
    rows = []
    for e in load_manifest():
        present = (skill_dir(e) / "SKILL.md").exists()
        rows.append(f"{'ok ' if present else 'MISSING'} {e['name']:<28} {e['target']:<6} {e['ref'][:10]}  {e['repo']}")
    return rows
