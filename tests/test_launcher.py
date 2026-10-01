"""Launcher: session discovery, worktree creation, plan -> claude args, and the menu flows."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from claude_harness import launcher as L


def write_session(projects: Path, sid: str, *, cwd: str, entry="cli", branch="main", custom=None, ai=None,
                  first="first prompt", last=None, mtime=None, filler_bytes=0):
    d = projects / ("-" + cwd.strip("/").replace("/", "-"))
    d.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "cwd": cwd, "entrypoint": entry, "gitBranch": branch, "message": {"role": "user", "content": first}}]
    if filler_bytes:
        lines += [{"type": "attachment", "pad": "x" * 1000}] * (filler_bytes // 1000)
    if ai:
        lines.append({"type": "ai-title", "aiTitle": ai})
    if custom:
        lines.append({"type": "custom-title", "customTitle": custom})
    if last:
        lines.append({"type": "last-prompt", "lastPrompt": last})
    lines.append({"type": "assistant", "cwd": cwd, "gitBranch": branch, "message": {"content": []}})
    f = d / f"{sid}.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    if mtime:
        os.utime(f, (mtime, mtime))
    return f


def test_recent_sessions_titles_filters_live_and_limit(tmp_path):
    claude = tmp_path / ".claude"; projects = claude / "projects"
    work = tmp_path / "work"; work.mkdir()
    now = time.time()
    write_session(projects, "s-custom", cwd=str(work), custom="Custom title", ai="AI title", last="did a thing", mtime=now - 10)
    write_session(projects, "s-ai", cwd=str(work), ai="AI only", mtime=now - 20)
    write_session(projects, "s-first", cwd=str(work), first="Just the first prompt\nmore", mtime=now - 30)
    write_session(projects, "s-sdk", cwd=str(work), entry="sdk-cli", custom="headless run", mtime=now - 5)
    write_session(projects, "s-gone", cwd=str(tmp_path / "deleted-worktree"), custom="Old worktree", mtime=now - 40)
    write_session(projects, "s-big", cwd=str(work), first="head prompt", custom="Title past 512KB", filler_bytes=700_000, mtime=now - 50)
    write_session(projects, "s-old", cwd=str(work), custom="sixth", mtime=now - 60)
    (projects / "-x" / "s-ai" / "subagents").mkdir(parents=True)   # nested transcripts are ignored
    (claude / "sessions").mkdir()
    (claude / "sessions" / f"{os.getpid()}.json").write_text(json.dumps({"pid": os.getpid(), "sessionId": "s-ai", "entrypoint": "claude-desktop"}))
    (claude / "sessions" / "999999.json").write_text(json.dumps({"pid": 999999, "sessionId": "s-first"}))   # dead pid

    got = L.recent_sessions(limit=5, claude_dir=claude)
    assert [s.id for s in got] == ["s-custom", "s-ai", "s-first", "s-gone", "s-big"]
    by = {s.id: s for s in got}
    assert by["s-custom"].title == "Custom title" and by["s-custom"].last_prompt == "did a thing"
    assert by["s-ai"].title == "AI only" and by["s-ai"].live_pid == os.getpid() and by["s-ai"].live_entry == "claude-desktop"
    assert by["s-first"].title == "Just the first prompt" and by["s-first"].live_pid is None
    assert by["s-big"].title == "Title past 512KB" and by["s-big"].cwd == str(work)
    assert not by["s-gone"].cwd_exists and L.session_option(by["s-gone"]).disabled


def _git(cwd, *a):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"; r.mkdir()
    _git(r, "init", "-q", "-b", "master")
    (r / "package.json").write_text("{}")
    _git(r, "add", "-A"); _git(r, "commit", "-qm", "init")
    _git(r, "checkout", "-qb", "feat/x"); (r / "x.txt").write_text("x"); _git(r, "add", "-A"); _git(r, "commit", "-qm", "x")
    _git(r, "checkout", "-q", "master")
    (r / "node_modules").mkdir()
    return r


def test_repo_info_and_create_worktree_from_chosen_base(repo):
    info = L.repo_info(repo)
    assert info.main == repo and info.branch == "master" and info.default_base == "master"
    assert info.branches[0] == "master" and "feat/x" in info.branches
    assert L.validate_name(info, "bad name!") and L.validate_name(info, "-dash")
    path, notes = L.create_worktree(info, "side", "feat/x")
    assert path == repo / ".claude" / "worktrees" / "side" and (path / "x.txt").exists()
    assert _git(path, "rev-parse", "--abbrev-ref", "HEAD") == "worktree-side"
    assert (path / "node_modules").is_symlink() and (path / "node_modules").resolve() == (repo / "node_modules").resolve()
    assert "**/.claude/worktrees/" in (repo / ".git" / "info" / "exclude").read_text()
    assert ".claude" not in _git(repo, "status", "--porcelain")
    assert "already exists" in L.validate_name(info, "side")
    # from inside the new worktree, worktrees still go under the MAIN checkout and default base stays master
    inner = L.repo_info(path)
    assert inner.main == repo and inner.branch == "worktree-side" and inner.default_base == "master"


def test_plan_args():
    assert L.LaunchPlan("new", "/w", "N", name="side").claude_args() == ["--session-id", "N", "--name", "side"]
    assert L.LaunchPlan("resume", "/w", "S", resume_id="S").claude_args() == ["--resume", "S"]
    assert L.LaunchPlan("fork", "/w", "N", resume_id="S").claude_args() == ["--resume", "S", "--fork-session", "--session-id", "N"]


def _sessions(tmp_path):
    w = tmp_path / "w"; w.mkdir(exist_ok=True)
    a = L.SessionInfo("sess-a", tmp_path / "a.jsonl", time.time() - 60, title="Alpha", last_prompt="go", cwd=str(w), branch="main", entry="cli")
    b = L.SessionInfo("sess-b", tmp_path / "b.jsonl", time.time() - 120, title="Beta", cwd=str(w), entry="claude-desktop", live_pid=123, live_entry="claude-desktop")
    return [a, b]


async def _run(app, keys, typed=None):
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause(0.2)
        for k in keys:
            await pilot.press(k); await pilot.pause(0.15)
        if typed is not None:
            inp = app.screen.query_one("#name")
            inp.value = typed
            await pilot.press("enter"); await pilot.pause(0.3)
    return app.return_value


async def test_launcher_new_here(repo, tmp_path):
    plan = await _run(L.LauncherApp(repo, sessions=_sessions(tmp_path)), ["enter", "enter"])
    assert plan.kind == "new" and plan.cwd == str(repo.resolve()) and len(plan.session_id) == 36


async def test_launcher_new_worktree(repo, tmp_path):
    plan = await _run(L.LauncherApp(repo, sessions=_sessions(tmp_path)), ["enter", "down", "enter", "down", "enter"], typed="my-task")
    assert plan.kind == "new" and plan.name == "my-task" and plan.cwd.endswith(".claude/worktrees/my-task")
    assert _git(plan.cwd, "rev-parse", "--abbrev-ref", "HEAD") == "worktree-my-task"


async def test_launcher_resume_and_fork(repo, tmp_path):
    plan = await _run(L.LauncherApp(repo, sessions=_sessions(tmp_path)), ["down", "enter"])
    assert plan.kind == "resume" and plan.resume_id == "sess-a" and plan.session_id == "sess-a"
    plan = await _run(L.LauncherApp(repo, sessions=_sessions(tmp_path)), ["down", "down", "enter", "enter"])
    assert plan.kind == "fork" and plan.resume_id == "sess-b" and plan.session_id != "sess-b"


async def test_launcher_quit_returns_none(repo, tmp_path):
    assert await _run(L.LauncherApp(repo, sessions=_sessions(tmp_path)), ["escape"]) is None
