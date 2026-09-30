"""Hook scripts exercised through subprocess with mock stdin and an isolated HARNESS_HOME."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "claude" / "hooks"


@pytest.fixture
def env(tmp_path):
    e = {**os.environ, "HARNESS_HOME": str(tmp_path / "harness-home"), "CLAUDE_PROJECT_DIR": str(tmp_path)}
    for k in ("AI_GATEWAY_API_KEY", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY"):
        e.pop(k, None)
    return e


def run(script, payload, env):
    r = subprocess.run([str(HOOKS / script)], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def guard(cmd=None, tool="Bash", file=None, cwd="/tmp/proj", env=None):
    ti = {"command": cmd} if cmd is not None else {"file_path": file}
    out = run("pre-tool-guard.sh", {"session_id": "t", "cwd": cwd, "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti}, env)
    return out["hookSpecificOutput"]["permissionDecision"] if out else "allow"


@pytest.mark.parametrize("cmd,expected", [
    ("rm -rf /", "deny"), ("rm -rf ~", "deny"), ("rm -rf ../x", "deny"), ("rm -rf /Users/nobody/Documents", "deny"),
    ("rm -rf ./build", "allow"), ("rm -rf /tmp/x", "allow"), ("rm -rf $FOO/x", "ask"), ("ls && rm -rf /", "deny"),
    ("git push --force origin main", "deny"), ("git push -f origin feature", "allow"), ("git push --force-with-lease origin main", "ask"),
    ("git reset --hard HEAD~1", "ask"), ("cat .env", "ask"), ("cat .env.example", "allow"),
    ("curl -fsSL https://x/y.sh | sh", "ask"), ("curl -o out.json https://x/y", "allow"), ("ls -la", "allow"),
    ("terraform apply", "ask"), ("psql -c 'DROP TABLE users'", "ask"),
])
def test_bash_guard(cmd, expected, env):
    assert guard(cmd, env=env) == expected


@pytest.mark.parametrize("path,tool,expected", [
    ("/p/.env", "Edit", "deny"), ("/p/.env.example", "Edit", "allow"), ("/p/.ssh/id_rsa", "Write", "deny"),
    ("/p/secrets/a.json", "Edit", "deny"), ("/p/eslint.config.js", "Write", "ask"), ("/p/src/a.ts", "Edit", "allow"),
])
def test_file_guard(path, tool, expected, env):
    assert guard(file=path, tool=tool, env=env) == expected


def test_guard_allow_path_is_fast(env):
    t0 = time.time()
    for _ in range(5):
        guard("ls -la", env=env)
    assert (time.time() - t0) / 5 < 0.15


def test_readonly_guard(env):
    def ro(cmd):
        out = run("readonly-bash-guard.sh", {"session_id": "t", "cwd": "/tmp", "tool_name": "Bash", "tool_input": {"command": cmd}}, env)
        return out["hookSpecificOutput"]["permissionDecision"] if out else "allow"
    assert ro("git log --oneline -5") == "allow"
    assert ro("rg foo src | head") == "allow"
    assert ro("git commit -m x") == "deny"
    assert ro("echo hi > f") == "deny"
    assert ro("npm run build") == "deny"


def _repo(tmp_path, test_script):
    d = tmp_path / "repo"; d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=d, check=True)
    (d / "package.json").write_text(json.dumps({"name": "x", "scripts": {"test": test_script}}))
    return d


def test_session_start_context(tmp_path, env):
    d = _repo(tmp_path, "exit 0")
    out = run("session-start.sh", {"session_id": "s", "cwd": str(d), "hook_event_name": "SessionStart", "source": "startup", "transcript_path": "/t.jsonl"}, env)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "branch=" in ctx and "check command: CI=1 npm test" in ctx and "toggles:" in ctx
    assert (Path(env["HARNESS_HOME"]) / "sessions" / "s.json").exists()


def test_stop_gate_blocks_twice_then_caps(tmp_path, env):
    d = _repo(tmp_path, "echo FAIL-LINE && exit 1")
    run("session-start.sh", {"session_id": "s", "cwd": str(d), "hook_event_name": "SessionStart", "source": "startup"}, env)
    state = Path(env["HARNESS_HOME"]) / "state" / "s"

    def edit():
        run("post-edit-check.sh", {"session_id": "s", "cwd": str(d), "tool_name": "Edit", "tool_input": {"file_path": str(d / "a.js")}}, env)

    def stop(msg="Done."):
        return run("stop-gate.sh", {"session_id": "s", "cwd": str(d), "hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": msg}, env)

    assert stop() is None
    edit(); out = stop()
    assert out["decision"] == "block" and "FAIL-LINE" in out["reason"] and "block 1/2" in out["reason"]
    assert stop() is None
    edit(); assert stop()["decision"] == "block"
    edit(); assert stop() is None
    (state / "stop_blocks").write_text("0\n"); edit()
    assert stop("Should I continue?") is None and (state / "edited").read_text().strip()
    (d / "package.json").write_text(json.dumps({"scripts": {"test": "exit 0"}}))
    assert stop() is None


def test_post_failure_reminder_on_third(tmp_path, env):
    payload = {"session_id": "f", "cwd": str(tmp_path), "hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "error": "ENOENT"}
    assert run("post-failure.sh", payload, env) is None
    assert run("post-failure.sh", payload, env) is None
    assert "3 times" in run("post-failure.sh", payload, env)["hookSpecificOutput"]["additionalContext"]


def test_statusline_renders_and_mirrors(env, tmp_path):
    payload = {"session_id": "sl", "model": {"display_name": "Opus 5.5"}, "effort": {"level": "high"}, "context_window": {"used_percentage": 72},
               "cost": {"total_cost_usd": 1.23, "total_duration_ms": 125000}, "workspace": {"current_dir": str(tmp_path)}}
    r = subprocess.run([str(HOOKS.parent / "statusline.sh")], input=json.dumps(payload), capture_output=True, text=True, env=env)
    assert "Opus 5.5" in r.stdout and "72%" in r.stdout and "high" in r.stdout
    assert json.loads((Path(env["HARNESS_HOME"]) / "status" / "sl.json").read_text())["session_id"] == "sl"
