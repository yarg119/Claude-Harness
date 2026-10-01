"""Headless dashboard tests: attach mode with synthetic data, and an embedded PTY that exits."""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="pty")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "hh"))
    for m in list(sys.modules):
        if m.startswith("claude_harness"):
            del sys.modules[m]
    from claude_harness import paths
    paths.ensure_dirs()
    sid = "11111111-2222-3333-4444-555555555555"
    (paths.HARNESS_HOME / "sessions" / f"{sid}.json").write_text(json.dumps({"session_id": sid, "cwd": str(tmp_path), "transcript_path": str(tmp_path / "t.jsonl")}))
    ev = paths.events_file(sid)
    ev.write_text("\n".join(json.dumps(e) for e in [
        {"ts": "2026-09-30T10:00:00", "ev": "SessionStart", "sid": sid, "cwd": str(tmp_path), "check": "npm test"},
        {"ts": "2026-09-30T10:00:01", "ev": "Prompt", "prompt": "refactor auth"},
        {"ts": "2026-09-30T10:00:02", "ev": "SubagentStart", "agent_id": "a1", "agent_type": "explorer"},
        {"ts": "2026-09-30T10:00:05", "ev": "Guard", "verdict": "deny", "reason": "rm -rf /"},
    ]) + "\n")
    (tmp_path / "t.jsonl").write_text(json.dumps({"type": "assistant", "timestamp": "2026-09-30T10:00:03Z", "effort": "high", "advisorModel": "claude-fable-5-1",
        "message": {"model": "claude-opus-5-5", "content": [{"type": "server_tool_use", "id": "s1", "name": "advisor", "input": {}},
        {"type": "advisor_tool_result", "tool_use_id": "s1", "content": {"type": "advisor_redacted_result"}}, {"type": "text", "text": "Plan verified."}],
        "usage": {"output_tokens": 10, "iterations": [{"type": "advisor_message", "input_tokens": 366000, "output_tokens": 700}]}}}) + "\n")
    paths.jev_file(sid).write_text(json.dumps({"ts": "2026-09-30T10:00:04", "fork": "route", "choice": "explorer", "p": 0.86, "verdict": "sharp"}) + "\n")
    paths.status_file(sid).write_text(json.dumps({"session_id": sid, "model": {"display_name": "Opus 5.5"}, "effort": {"level": "high"}, "context_window": {"used_percentage": 23, "context_window_size": 1000000}, "cost": {"total_cost_usd": 1.5}}))
    return sid


async def test_attach_mode_renders(home):
    from claude_harness.app import HarnessApp
    from claude_harness.widgets.panels import AdvisorPanel, JevPanel, StatusBar
    app = HarnessApp(home, None, None)
    async with app.run_test(size=(120, 48)) as pilot:
        await pilot.pause(0.6)
        s = app.state
        assert s.advisor.calls == 1 and s.advisor.tokens_read == 366000 and s.jev["route"].sharp == 1
        assert s.agent_for_kind("explorer") is not None and s.ctx_pct == 23 and s.guard_denies == 1
        assert "366k" in app.query_one(AdvisorPanel).render_state(s).plain
        assert "which worker" in app.query_one(JevPanel).render_state(s).plain
        assert "ctx 23%" in app.query_one(StatusBar).render_state(s).plain
        await pilot.press("f1")
        assert not app.query_one("#help").has_class("hidden")


async def test_embedded_pty_runs_and_exits(home):
    from claude_harness.app import HarnessApp
    from claude_harness.widgets.terminal_pane import TerminalPane
    app = HarnessApp(home, ["bash", "-c", "echo HARNESS_PTY_OK; exit 3"], "split")
    async with app.run_test(size=(180, 48)) as pilot:
        for _ in range(40):
            await pilot.pause(0.25)
            if app._exited:
                break
        assert app._exited and app.query_one(TerminalPane).exit_code == 3
        assert app.mode == "split"


async def test_tabs_mode_starts_on_tree_and_fits_90x46(home):
    import html, re
    from claude_harness.app import HarnessApp
    app = HarnessApp(home, ["bash", "-c", "sleep 30"], "tabs")
    async with app.run_test(size=(90, 46)) as pilot:
        await pilot.pause(0.6)
        assert app.mode == "tabs" and app.showing == "tree"
        text = html.unescape(re.sub(r"<[^>]+>", "", app.export_screenshot())).replace("\xa0", " ")
        for needle in ("AGENT TREE", "Fable · on call", "Sonnet 5.5 · medium", "SONNET 5.5 · DISPATCHER", "which worker", "back to main session", "session log", "codex: [", "F2"):
            assert needle in text, needle
        await pilot.press("f2"); await pilot.pause(0.2)
        assert app.showing == "tty" and app.state.claude_visible
        await pilot.press("f2"); await pilot.pause(0.2)
        assert app.showing == "tree" and not app.state.claude_visible
        await pilot.press("f10")


async def test_split_mode_f2_hides_and_shows_claude(home):
    from claude_harness.app import HarnessApp
    app = HarnessApp(home, ["bash", "-c", "sleep 30"], "split")
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.pause(0.5)
        assert app.mode == "split" and not app.state.claude_visible          # tree first
        await pilot.press("f2"); await pilot.pause(0.2)
        assert app.state.claude_visible and not app.query_one("#tree").has_class("hidden")
        await pilot.press("f2"); await pilot.pause(0.2)                       # pressed while the terminal has focus
        assert not app.state.claude_visible and app.query_one("#tty-pane").has_class("hidden")
        await pilot.press("f3"); await pilot.pause(0.2)
        assert app.state.claude_visible and app.query_one("#tree").has_class("hidden")
        await pilot.press("f3"); await pilot.pause(0.2)
        assert not app.query_one("#tree").has_class("hidden")
        await pilot.press("f10")


MOUSE_CHILD = """
import os, sys, termios, tty, time
log = open(sys.argv[1], "wb"); fd = sys.stdin.fileno(); tty.setraw(fd)
sys.stdout.write("\\x1b[?1049h\\x1b[?1002h\\x1b[?1006h"); sys.stdout.flush()
os.set_blocking(fd, False); end = time.time() + 15
while time.time() < end:
    try:
        b = os.read(fd, 1024)
        if b: log.write(b); log.flush()
    except BlockingIOError: time.sleep(0.02)
"""


async def test_mouse_wheel_reaches_a_mouse_tracking_child(home, tmp_path):
    """Regression: bittty reports mouse tracking via on_mouse_capture; without the bridge the
    pane dropped every wheel event and claude's fullscreen transcript could not be scrolled."""
    import sys
    from textual import events
    from claude_harness.app import HarnessApp
    child = tmp_path / "mouse_child.py"; child.write_text(MOUSE_CHILD); log = tmp_path / "bytes.bin"
    app = HarnessApp(home, [sys.executable, str(child), str(log)], "split")
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.press("f2")
        tty = app.query_one("#tty")
        for _ in range(30):
            await pilot.pause(0.1)
            if tty.mouse_mode != "off":
                break
        assert tty.mouse_mode == "button"
        tty.post_message(events.MouseScrollUp(tty, 10, 5, 0, -1, 0, False, False, False, screen_x=10, screen_y=5))
        await pilot.pause(0.2)
        await pilot.press("pageup"); await pilot.pause(0.3)
        data = log.read_bytes()
        assert b"\x1b[<64;" in data and b"\x1b[5~" in data
        await pilot.press("f10")



async def test_drag_leaving_the_pane_still_releases_and_textual_selects_nothing(home, tmp_path):
    """Regression: a drag that ended outside the pane never sent the release, so claude kept
    extending its selection ("highlights the entire screen"); Textual also selected across panels."""
    import sys
    from claude_harness.app import HarnessApp
    child = tmp_path / "mouse_child.py"; child.write_text(MOUSE_CHILD); log = tmp_path / "bytes.bin"
    app = HarnessApp(home, [sys.executable, str(child), str(log)], "split")
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.press("f2")
        tty = app.query_one("#tty"); tree = app.query_one("#tree")
        for _ in range(30):
            await pilot.pause(0.1)
            if tty.mouse_mode != "off":
                break
        await pilot.mouse_down(tty, offset=(5, 3)); await pilot.hover(tty, offset=(30, 10))
        await pilot.hover(tree, offset=(10, 10)); await pilot.mouse_up(tree, offset=(10, 10))
        await pilot.pause(0.3)
        data = log.read_bytes()
        assert data.count(b"m") >= 1 and data.rstrip().endswith(b"m"), data[-60:]
        assert data.count(b";11m") == 1 and data.count(b"<0;6;4M") == 1   # one press, one release clamped to the pane edge
        assert not app.screen.selections
        await pilot.press("f10")


async def test_textual_selection_is_off_without_a_tracking_child(home):
    from claude_harness.app import HarnessApp
    app = HarnessApp(home, ["bash", "-c", "seq 1 60; sleep 20"], "split")
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.press("f2"); await pilot.pause(0.8)
        tty = app.query_one("#tty"); tree = app.query_one("#tree")
        await pilot.mouse_down(tty, offset=(2, 2)); await pilot.hover(tree, offset=(10, 10)); await pilot.mouse_up(tree, offset=(10, 10))
        await pilot.pause(0.2)
        assert not app.screen.selections and not (app.screen.get_selected_text() or "")
        await pilot.press("f10")
