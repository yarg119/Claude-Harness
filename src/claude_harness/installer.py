"""Install/uninstall the harness into ~/.claude and ~/.codex. Backups before every in-place write."""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import config, paths
from .merge import deep_merge, drop_hook_groups

PM_BEGIN, PM_END = "<!-- puppetmaster:rules:begin -->", "<!-- puppetmaster:rules:end -->"
HB_BEGIN, HB_END = "<!-- claude-harness:begin -->", "<!-- claude-harness:end -->"
IMPORT_LINE = "@~/.claude/HARNESS.md"


class Log(list):
    def __call__(self, msg: str) -> None:
        self.append(msg)


def _ts() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


class Backups:
    def __init__(self, dry: bool):
        self.dry = dry
        self.dir = paths.HARNESS_HOME / "backups" / _ts()

    def save(self, p: Path, log: Log) -> None:
        if not p.exists():
            return
        if self.dry:
            log(f"[dry] backup {p} -> {self.dir}")
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        dest = self.dir / p.name if p.parent == paths.HOME else self.dir / (p.parent.name + "-" + p.name)
        shutil.copy2(p, dest)
        log(f"backup {p} -> {dest}")


def harness_bin() -> str:
    for cand in (paths.HOME / ".local" / "bin" / "harness", Path(shutil.which("harness") or "")):
        if cand and cand.exists():
            return str(cand)
    return "harness"


def render(text: str) -> str:
    return (text.replace("__HOME__", str(paths.HOME))
                .replace("__HOOKS__", str(paths.CLAUDE_DIR / "hooks"))
                .replace("__HARNESS_BIN__", harness_bin()))


def _link(target: Path, link: Path, log: Log, dry: bool, force: bool = False) -> None:
    if link.is_symlink():
        if link.resolve() == target.resolve():
            return
        if not force and not str(link.resolve()).startswith(str(paths.REPO)):
            log(f"skip {link}: symlink to foreign target {link.resolve()} (use --force)")
            return
    elif link.exists():
        if not force:
            log(f"skip {link}: exists and is not a symlink (use --force to replace)")
            return
        if dry:
            log(f"[dry] replace {link}")
        else:
            bak = link.with_name(link.name + f".bak-{_ts()}")
            link.rename(bak)
            log(f"moved {link} -> {bak}")
    if dry:
        log(f"[dry] link {link} -> {target}")
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        link.unlink()
    link.symlink_to(target)
    log(f"link {link} -> {target}")


def _write_if_changed(p: Path, content: str, bk: Backups, log: Log, dry: bool) -> bool:
    old = p.read_text() if p.exists() else None
    if old == content:
        log(f"unchanged {p}")
        return False
    bk.save(p, log)
    if dry:
        log(f"[dry] write {p}")
        return True
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    log(f"wrote {p}")
    return True


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _dump(d: dict) -> str:
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def link_claude_files(log: Log, dry: bool, force: bool) -> None:
    src = paths.REPO_CLAUDE
    for f in sorted((src / "agents").glob("*.md")):
        _link(f, paths.CLAUDE_DIR / "agents" / f.name, log, dry, force)
    for d in sorted((src / "skills").iterdir()):
        if d.is_dir():
            _link(d, paths.CLAUDE_DIR / "skills" / d.name, log, dry, force)
    for f in sorted((src / "rules").glob("*.md")):
        _link(f, paths.CLAUDE_DIR / "rules" / f.name, log, dry, force)
    hooks_link = paths.CLAUDE_DIR / "hooks"
    if hooks_link.exists() and not hooks_link.is_symlink():
        for f in sorted((src / "hooks").glob("*.sh")):
            _link(f, hooks_link / f.name, log, dry, force)
    else:
        _link(src / "hooks", hooks_link, log, dry, force)
    _link(src / "statusline.sh", paths.CLAUDE_DIR / "statusline.sh", log, dry, force)
    _link(src / "CLAUDE.md", paths.CLAUDE_DIR / "HARNESS.md", log, dry, force)
    for f in list((src / "hooks").glob("*.sh")) + [src / "statusline.sh"]:
        os.chmod(f, 0o755)


def ensure_claude_md_import(bk: Backups, log: Log, dry: bool) -> None:
    p = paths.CLAUDE_DIR / "CLAUDE.md"
    if not p.exists():
        _write_if_changed(p, IMPORT_LINE + "\n", bk, log, dry)
        return
    text = p.read_text()
    if any(line.strip() == IMPORT_LINE for line in text.splitlines()):
        log(f"unchanged {p} (import present)")
        return
    _write_if_changed(p, text.rstrip("\n") + "\n\n" + IMPORT_LINE + "\n", bk, log, dry)


def merge_settings(bk: Backups, log: Log, dry: bool, remove_puppetmaster: bool) -> None:
    base = _load_json(paths.SETTINGS)
    fragment = json.loads(render((paths.REPO_CLAUDE / "settings.fragment.json").read_text()))
    base = drop_hook_groups(base, str(paths.CLAUDE_DIR / "hooks"))
    if remove_puppetmaster:
        base = drop_hook_groups(base, "puppetmaster")
    merged = deep_merge(base, fragment)
    _write_if_changed(paths.SETTINGS, _dump(merged), bk, log, dry)


def remove_puppetmaster(bk: Backups, log: Log, dry: bool) -> None:
    # 1. MCP server registration (user scope lives in ~/.claude.json)
    cj = _load_json(paths.CLAUDE_JSON)
    if "puppetmaster" in (cj.get("mcpServers") or {}):
        bk.save(paths.CLAUDE_JSON, log)
        if dry:
            log("[dry] claude mcp remove puppetmaster -s user")
        else:
            r = subprocess.run(["claude", "mcp", "remove", "puppetmaster", "-s", "user"], capture_output=True, text=True)
            if r.returncode == 0 and "puppetmaster" not in (_load_json(paths.CLAUDE_JSON).get("mcpServers") or {}):
                log("removed MCP server puppetmaster (claude mcp remove)")
            else:
                cj = _load_json(paths.CLAUDE_JSON)
                cj.get("mcpServers", {}).pop("puppetmaster", None)
                paths.CLAUDE_JSON.write_text(_dump(cj))
                log("removed MCP server puppetmaster (edited ~/.claude.json)")
    else:
        log("puppetmaster MCP server: not registered")
    # 2. Managed blocks in AGENTS.md files
    for p in (paths.HOME / "AGENTS.md", paths.CODEX_DIR / "AGENTS.md"):
        if not p.exists():
            continue
        text = p.read_text()
        if PM_BEGIN not in text:
            continue
        new = re.sub(re.escape(PM_BEGIN) + r".*?" + re.escape(PM_END) + r"\n?", "", text, flags=re.S).strip("\n")
        bk.save(p, log)
        if dry:
            log(f"[dry] strip puppetmaster block from {p}" + (" and delete (empty)" if not new.strip() else ""))
            continue
        if new.strip():
            p.write_text(new + "\n")
            log(f"stripped puppetmaster block from {p}")
        else:
            p.unlink()
            log(f"deleted {p} (only contained the puppetmaster block)")


def _replace_block(text: str, block: str) -> str:
    block = block.strip("\n")
    if HB_BEGIN in text and HB_END in text:
        return re.sub(re.escape(HB_BEGIN) + r".*?" + re.escape(HB_END), block, text, flags=re.S)
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + block + "\n"


def install_codex(bk: Backups, log: Log, dry: bool, force: bool) -> None:
    paths.CODEX_DIR.mkdir(exist_ok=True)
    _link(paths.REPO_CODEX / "harness.config.toml", paths.CODEX_DIR / "harness.config.toml", log, dry, force)
    base = _load_json(paths.CODEX_DIR / "hooks.json")
    fragment = json.loads(render((paths.REPO_CODEX / "hooks.json").read_text()))
    base = drop_hook_groups(base, str(paths.CLAUDE_DIR / "hooks"))
    _write_if_changed(paths.CODEX_DIR / "hooks.json", _dump(deep_merge(base, fragment)), bk, log, dry)
    agents = paths.CODEX_DIR / "AGENTS.md"
    block = render((paths.REPO_CODEX / "AGENTS.md").read_text())
    _write_if_changed(agents, _replace_block(agents.read_text() if agents.exists() else "", block), bk, log, dry)
    if not dry and shutil.which("codex"):
        r = subprocess.run(["codex", "features", "enable", "hooks"], capture_output=True, text=True)
        log("codex features enable hooks: " + ("ok" if r.returncode == 0 else (r.stderr or r.stdout).strip()[:120]))
    log("NOTE: open `codex`, run /hooks and trust the harness hooks once (hash-pinned).")


def install(with_codex: bool, remove_pm: bool, dry: bool = False, force: bool = False) -> Log:
    log = Log()
    bk = Backups(dry)
    paths.ensure_dirs()
    link_claude_files(log, dry, force)
    ensure_claude_md_import(bk, log, dry)
    merge_settings(bk, log, dry, remove_pm)
    if remove_pm:
        remove_puppetmaster(bk, log, dry)
    if with_codex:
        install_codex(bk, log, dry, force)
    cfg = config.load()
    if not dry:
        cfg.setdefault("installed_at", _dt.datetime.now().isoformat(timespec="seconds"))
        cfg["codex"] = bool(with_codex) if "codex" not in cfg or cfg["codex"] is False else cfg["codex"]
        config.save(cfg)
        set_codex(bool(cfg["codex"]), log)
    log("next: harness doctor")
    return log


def uninstall(dry: bool = False) -> Log:
    log = Log()
    bk = Backups(dry)
    for link in [*(paths.CLAUDE_DIR / "agents").glob("*.md"), *(paths.CLAUDE_DIR / "skills").iterdir(),
                 *(paths.CLAUDE_DIR / "rules").glob("*.md"), paths.CLAUDE_DIR / "hooks",
                 paths.CLAUDE_DIR / "statusline.sh", paths.CLAUDE_DIR / "HARNESS.md",
                 paths.CODEX_DIR / "harness.config.toml"]:
        if link.is_symlink() and str(link.resolve()).startswith(str(paths.REPO)):
            log(("[dry] " if dry else "") + f"unlink {link}")
            if not dry:
                link.unlink()
    base = _load_json(paths.SETTINGS)
    base = drop_hook_groups(base, str(paths.CLAUDE_DIR / "hooks"))
    for k in ("statusLine",):
        base.pop(k, None)
    _write_if_changed(paths.SETTINGS, _dump(base), bk, log, dry)
    ch = _load_json(paths.CODEX_DIR / "hooks.json")
    if ch:
        _write_if_changed(paths.CODEX_DIR / "hooks.json", _dump(drop_hook_groups(ch, str(paths.CLAUDE_DIR / "hooks"))), bk, log, dry)
    log("kept: model/advisor/effort settings, ~/.claude/CLAUDE.md import line, backups under " + str(paths.HARNESS_HOME / "backups"))
    return log


def set_codex(on: bool, log: Log | None = None) -> Log:
    log = log or Log()
    bk = Backups(False)
    s = _load_json(paths.SETTINGS)
    plugins = s.setdefault("enabledPlugins", {})
    if plugins.get("codex@openai-codex") != on:
        plugins["codex@openai-codex"] = on
        _write_if_changed(paths.SETTINGS, _dump(s), bk, log, False)
    config.set_value("codex", on)
    log(f"codex: {'on' if on else 'off'} (plugin {'enabled' if on else 'disabled'}; takes effect in new sessions)")
    return log


def set_jev(on: bool) -> Log:
    log = Log()
    if on and not (os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("TYPESAFE_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or _env_file_has_key()):
        log("WARN: no AI_GATEWAY_API_KEY / TYPESAFE_API_KEY / OPENROUTER_API_KEY in the environment or ~/.claude/harness/env; hooks will skip Jev.")
    config.set_value("jev", on)
    log(f"jev: {'on' if on else 'off'}")
    return log


def _env_file_has_key() -> bool:
    p = paths.HARNESS_HOME / "env"
    try:
        return bool(re.search(r"^(export\s+)?(AI_GATEWAY_API_KEY|TYPESAFE_API_KEY|OPENROUTER_API_KEY)=", p.read_text(), re.M))
    except OSError:
        return False


def init_project(dest: Path) -> Log:
    log = Log()
    dest = dest.resolve()
    for src in sorted(paths.REPO_TEMPLATE.rglob("*")):
        rel = src.relative_to(paths.REPO_TEMPLATE)
        out = dest / rel
        if src.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        if out.exists():
            log(f"exists  {rel}")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        log(f"created {rel}")
    log("next: edit AGENTS.md and .claude/harness.json (check command), then `harness run` here")
    return log
