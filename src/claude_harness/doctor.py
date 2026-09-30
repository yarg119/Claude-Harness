"""Health checks for the installed harness, plus the model tree."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

from . import config, paths

DISABLING_ENV = ("DISABLE_TELEMETRY", "CLAUDE_CODE_DISABLE_ADVISOR_TOOL", "CLAUDE_CODE_EFFORT_LEVEL",
                 "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")


@dataclass
class Check:
    name: str
    status: str  # PASS WARN FAIL SKIP
    detail: str = ""


def _run(cmd: list[str], timeout: float = 15, inp: str | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=inp)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def _settings() -> dict:
    try:
        return json.loads(paths.SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def _hook_cmds(settings: dict, event: str) -> list[str]:
    return [h.get("command", "") for g in settings.get("hooks", {}).get(event, []) for h in g.get("hooks", [])]


def run_checks(live: bool = True) -> list[Check]:
    s = _settings()
    cfg = config.load()
    out: list[Check] = []
    hooks_dir = paths.CLAUDE_DIR / "hooks"

    rc, v = _run(["claude", "--version"])
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", v)
    ok = bool(m) and tuple(map(int, m.groups())) >= (2, 1, 257)
    out.append(Check("claude version >= 2.1.257 (Fable 5.1 advisor)", "PASS" if ok else "FAIL", v.split("\n")[0]))

    out.append(Check("advisorModel = fable", "PASS" if s.get("advisorModel") == "fable" else "FAIL", str(s.get("advisorModel"))))
    ms = (s.get("modelSettings") or {}).get("claude-opus-5-5", {}).get("effortLevel")
    out.append(Check("modelSettings claude-opus-5-5 effort = high", "PASS" if ms == "high" else "FAIL", str(ms)))
    out.append(Check("model default", "PASS" if s.get("model") in ("opus", "opus[1m]") else "WARN", str(s.get("model"))))

    bad = [k for k in DISABLING_ENV if os.environ.get(k)] + [k for k in DISABLING_ENV if (s.get("env") or {}).get(k)]
    rc_files = []
    for f in (".zshrc", ".zprofile", ".zshenv", ".profile", ".bashrc"):
        p = paths.HOME / f
        try:
            if re.search(r"^\s*(export\s+)?(" + "|".join(DISABLING_ENV) + r")=", p.read_text(), re.M):
                rc_files.append(f)
        except OSError:
            pass
    out.append(Check("no advisor/effort-disabling env vars", "PASS" if not bad and not rc_files else "FAIL",
                     ", ".join(bad + [f"~/{f}" for f in rc_files]) or "clean"))

    sl = (s.get("statusLine") or {}).get("command", "")
    slp = paths.CLAUDE_DIR / "statusline.sh"
    out.append(Check("statusLine wired + executable", "PASS" if sl == str(slp) and os.access(slp, os.X_OK) else "FAIL", sl or "unset"))
    mock = json.dumps({"session_id": "doctor", "model": {"display_name": "Opus 5.5"}, "effort": {"level": "high"},
                       "context_window": {"used_percentage": 12}, "cost": {"total_cost_usd": 0.12, "total_duration_ms": 61000},
                       "workspace": {"current_dir": str(paths.HOME)}})
    rc, o = _run([str(slp)], inp=mock) if slp.exists() else (1, "missing")
    out.append(Check("statusLine renders", "PASS" if rc == 0 and "Opus 5.5" in o else "FAIL", re.sub(r"\x1b\[[0-9;]*m", "", o)[:100]))

    for a in ("explorer", "worker", "researcher", "reviewer"):
        p = paths.CLAUDE_DIR / "agents" / f"{a}.md"
        try:
            t = p.read_text()
            good = p.is_symlink() and re.search(r"^model: sonnet$", t, re.M) and re.search(r"^effort: medium$", t, re.M)
        except OSError:
            good = False
        out.append(Check(f"agent {a}: sonnet/medium", "PASS" if good else "FAIL", str(p) if good else "missing or wrong frontmatter"))

    for h in ("session-start", "user-prompt", "pre-tool-guard", "post-edit-check", "post-failure", "stop-gate", "pre-compact", "emit", "readonly-bash-guard"):
        p = hooks_dir / f"{h}.sh"
        out.append(Check(f"hook {h}.sh executable", "PASS" if os.access(p, os.X_OK) else "FAIL", str(p)))
    for ev, needle in (("SessionStart", "session-start"), ("UserPromptSubmit", "user-prompt"), ("PreToolUse", "pre-tool-guard"),
                       ("PostToolUse", "post-edit-check"), ("PostToolUseFailure", "post-failure"), ("Stop", "stop-gate"), ("PreCompact", "pre-compact")):
        out.append(Check(f"hook registered: {ev} -> {needle}", "PASS" if any(needle in c for c in _hook_cmds(s, ev)) else "FAIL"))

    guard = hooks_dir / "pre-tool-guard.sh"
    if guard.exists():
        env = {**os.environ, "HARNESS_HOME": str(paths.HARNESS_HOME)}
        def g(cmd: str) -> str:
            r = subprocess.run([str(guard)], input=json.dumps({"session_id": "doctor", "cwd": "/tmp", "tool_name": "Bash", "tool_input": {"command": cmd}}),
                               capture_output=True, text=True, env=env)
            try:
                return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"]
            except (ValueError, KeyError):
                return "allow"
        out.append(Check("guard denies rm -rf /", "PASS" if g("rm -rf /") == "deny" else "FAIL"))
        t0 = time.time(); allow = g("ls -la"); ms = (time.time() - t0) * 1000
        out.append(Check("guard allows ls (fast)", "PASS" if allow == "allow" and ms < 80 else "WARN", f"{ms:.0f} ms"))

    pm_hooks = [c for ev in s.get("hooks", {}) for c in _hook_cmds(s, ev) if "puppetmaster" in c]
    try:
        pm_mcp = "puppetmaster" in (json.loads(paths.CLAUDE_JSON.read_text()).get("mcpServers") or {})
    except (OSError, ValueError):
        pm_mcp = False
    pm_agents = []
    for p in (paths.HOME / "AGENTS.md", paths.CODEX_DIR / "AGENTS.md", paths.Path.cwd() / "AGENTS.md"):
        try:
            if "puppetmaster:rules:begin" in p.read_text():
                pm_agents.append(str(p))
        except OSError:
            pass
    residue = (["hooks"] if pm_hooks else []) + (["mcp"] if pm_mcp else []) + pm_agents
    out.append(Check("puppetmaster removed", "PASS" if not residue else "WARN", ", ".join(residue) or "no residue"))

    for sk in ("plan-contract", "done", "checkpoint", "gc", "harness"):
        p = paths.CLAUDE_DIR / "skills" / sk / "SKILL.md"
        out.append(Check(f"skill /{sk}", "PASS" if p.exists() else "FAIL"))
    for r in ("harness-delegation", "harness-advisor", "harness-verification"):
        out.append(Check(f"rule {r}", "PASS" if (paths.CLAUDE_DIR / "rules" / f"{r}.md").exists() else "FAIL"))
    cm = paths.CLAUDE_DIR / "CLAUDE.md"
    try:
        imp = "@~/.claude/HARNESS.md" in cm.read_text() and (paths.CLAUDE_DIR / "HARNESS.md").exists()
    except OSError:
        imp = False
    out.append(Check("~/.claude/CLAUDE.md imports HARNESS.md", "PASS" if imp else "FAIL"))

    hb = shutil.which("harness") or (str(paths.HOME / ".local/bin/harness") if (paths.HOME / ".local/bin/harness").exists() else "")
    out.append(Check("harness CLI on PATH (hooks call it for Jev)", "PASS" if hb else "WARN", hb or "run: uv tool install --editable " + str(paths.REPO)))

    codex_on = bool((s.get("enabledPlugins") or {}).get("codex@openai-codex"))
    out.append(Check("codex toggle", "PASS", f"{'on' if cfg.get('codex') else 'off'} (plugin {'enabled' if codex_on else 'disabled'})"))
    if shutil.which("codex"):
        rc, v = _run(["codex", "--version"]); out.append(Check("codex cli", "PASS" if rc == 0 else "WARN", v[:60]))
        rc, a = _run(["codex", "login", "status"]); out.append(Check("codex auth", "PASS" if "Logged in" in a else "WARN", a[:80]))
        hj = paths.CODEX_DIR / "hooks.json"
        try:
            hooks_ok = any(str(hooks_dir) in c for ev in json.loads(hj.read_text()).get("hooks", {}) for c in _hook_cmds(json.loads(hj.read_text()), ev))
        except (OSError, ValueError):
            hooks_ok = False
        out.append(Check("codex hooks.json mirrors harness hooks", "PASS" if hooks_ok else "SKIP", "trust them once via /hooks in codex" if hooks_ok else "run: harness install --with-codex"))
        out.append(Check("codex profile ~/.codex/harness.config.toml", "PASS" if (paths.CODEX_DIR / "harness.config.toml").exists() else "SKIP", "use: codex -p harness"))
        try:
            ab = "claude-harness:begin" in (paths.CODEX_DIR / "AGENTS.md").read_text()
        except OSError:
            ab = False
        out.append(Check("codex AGENTS.md harness block", "PASS" if ab else "SKIP"))
    else:
        out.append(Check("codex cli", "SKIP", "not installed"))

    has_key = bool(os.environ.get("TYPESAFE_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))
    envf = paths.HARNESS_HOME / "env"
    try:
        has_key = has_key or bool(re.search(r"^(export\s+)?(TYPESAFE_API_KEY|OPENROUTER_API_KEY)=", envf.read_text(), re.M))
    except OSError:
        pass
    out.append(Check("jev toggle + key", "PASS" if (not cfg.get("jev") or has_key) else "FAIL",
                     f"{'on' if cfg.get('jev') else 'off'}, key {'found' if has_key else 'missing'}"))
    if live and cfg.get("jev") and has_key:
        try:
            from . import jev
            r = jev.ping()
            out.append(Check("jev live decision", "PASS" if r.get("ok") else "FAIL", r.get("detail", "")[:100]))
        except Exception as e:  # noqa: BLE001
            out.append(Check("jev live decision", "FAIL", str(e)[:100]))
    try:
        import textual_tty  # noqa: F401
        out.append(Check("textual-tty importable (embedded PTY)", "PASS"))
    except Exception as e:  # noqa: BLE001
        out.append(Check("textual-tty importable (embedded PTY)", "WARN", str(e)[:80]))
    return out


def model_tree() -> str:
    s = _settings(); cfg = config.load()
    eff = (s.get("modelSettings") or {}).get("claude-opus-5-5", {}).get("effortLevel", "medium(default)")
    seff = (s.get("modelSettings") or {}).get("claude-sonnet-5-5", {}).get("effortLevel", "medium(default)")
    lines = [
        f"Claude Code  main={s.get('model', 'default')} (Opus 5.5, effort {eff})  advisor={s.get('advisorModel', 'off')} (Fable 5.1)",
        f"  ├─ explorer    sonnet/medium  read-only code exploration",
        f"  ├─ worker      sonnet/medium  edits + runs the check command",
        f"  ├─ researcher  sonnet/medium  docs via context7 / WebFetch",
        f"  ├─ reviewer    sonnet/medium  adversarial second pass",
        f"  ├─ jev         {'on ' if cfg.get('jev') else 'off'}  forks: route / tool_risk / retry_or_stop (threshold {cfg.get('jev_threshold')})",
        f"  └─ codex       {'on ' if cfg.get('codex') else 'off'}  /codex:adversarial-review in /done, /codex:rescue on demand",
        f"  sonnet default effort: {seff}",
    ]
    return "\n".join(lines)


def report(live: bool = True) -> tuple[str, int]:
    checks = run_checks(live)
    width = max(len(c.name) for c in checks)
    colors = {"PASS": "\x1b[32m", "WARN": "\x1b[33m", "FAIL": "\x1b[31m", "SKIP": "\x1b[2m"}
    lines = [f"{colors[c.status]}{c.status:4}\x1b[0m  {c.name:<{width}}  {c.detail}" for c in checks]
    fails = sum(c.status == "FAIL" for c in checks)
    warns = sum(c.status == "WARN" for c in checks)
    lines += ["", model_tree(), "", f"{fails} FAIL, {warns} WARN, {len(checks)} checks"]
    return "\n".join(lines), (1 if fails else 0)
