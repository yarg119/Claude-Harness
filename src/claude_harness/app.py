"""Textual app: agent-tree dashboard with an optional embedded `claude` PTY."""
from __future__ import annotations

import os

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Static

from . import config, paths
from .sources.events import JsonlTail, latest_session_id, session_info
from .sources.jevlog import JevTail
from .sources.status import read_status
from .sources.transcript import TranscriptTail
from .state import SessionState
from .widgets.panels import TreeView
from .widgets.terminal_pane import TerminalPane

HELP = """[b]harness[/b]  F1 help · F2 show/hide the claude pane · F3 claude full screen · F10 quit (also ends claude)
Wide terminals (≥160 cols) show claude beside the tree; narrower ones flip between them. Typing on the tree brings claude up.
Toggles: `harness codex on|off`, `harness jev on|off`. Fallback: `harness run --layout tmux` or `harness attach`."""


class HarnessApp(App):
    CSS = """
    Screen { background: #101117; color: #e6e6ea; }
    #root { height: 100%; }
    #tree { width: 40%; min-width: 88; height: 100%; }
    #tree.full { width: 100%; }
    #tty-pane.zoom { width: 100%; }
    .hidden { display: none; }
    #help { dock: bottom; height: 4; background: #1c1d27; padding: 0 1; }
    #exit-note { dock: bottom; height: 1; background: #3a2d2d; color: #ffd0d0; padding: 0 1; }
    """
    BINDINGS = [
        Binding("f1", "help", "help", priority=True),
        Binding("f2", "switch", "view", priority=True),
        Binding("f3", "zoom", "zoom", priority=True),
        Binding("f10", "quit_app", "quit", priority=True),
    ]

    def __init__(self, session_id: str | None, command: list[str] | None, layout: str | None):
        super().__init__()
        self.session_id = session_id or latest_session_id() or ""
        self.command = command
        self.layout_pref = layout or config.load().get("layout") or "auto"
        self.mode = "split"; self.zoomed = False; self.showing = "tree"   # tree first; F2 shows/hides claude
        self.claude_shown = False   # split mode: is the claude pane on screen
        self.state = SessionState(session_id=self.session_id)
        self.state.embedded = bool(command)
        try:
            import json
            self.state.advisor.model = str(json.load(open(paths.SETTINGS)).get("advisorModel") or "")
        except (OSError, ValueError):
            pass
        self.state.launch_cmd = " ".join(c for c in (command or []) if not c.startswith("--session-id") and len(c) != 36)
        self.state.apply_config(config.load())
        self._events = JsonlTail(paths.events_file(self.session_id)) if self.session_id else None
        self._jev = JevTail(self.session_id) if self.session_id else None
        self._transcript = TranscriptTail(self.session_id, os.getcwd()) if self.session_id else None
        self._exited = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="root"):
            if self.command:
                yield TerminalPane(self.command, env={"HARNESS_SESSION_ID": self.session_id}, id="tty-pane")
            yield TreeView(id="tree")
        yield Static(HELP, id="help", classes="hidden")

    def on_mount(self) -> None:
        self.title = "harness"
        self._apply_layout()
        self.set_interval(0.25, self._poll)


    # ---- layout ----
    def _apply_layout(self) -> None:
        if not self.command:
            self.mode = "full"
        elif self.layout_pref in ("split", "tabs"):
            self.mode = self.layout_pref
        else:
            self.mode = "split" if self.size.width >= 160 else "tabs"
        tree = self.query_one("#tree")
        if self.mode == "full":
            tree.add_class("full"); return
        tty = self.query_one("#tty-pane")
        if self.mode == "tabs":
            show_tty = self.showing == "tty"
            show_tree = not show_tty
        else:  # split: F2 toggles the claude pane, F3 zooms it
            show_tty = self.claude_shown or self.zoomed
            show_tree = not self.zoomed
        tty.set_class(not show_tty, "hidden"); tree.set_class(not show_tree, "hidden")
        tree.set_class(not show_tty, "full")
        self.state.claude_visible = show_tty
        if show_tty:
            self.query_one(TerminalPane).focus_tty()

    def on_resize(self) -> None:
        if self.layout_pref == "auto":
            self._apply_layout()

    def action_help(self) -> None:
        self.query_one("#help").toggle_class("hidden")

    def action_switch(self) -> None:
        """F2: show/hide the claude pane."""
        if not self.command:
            return
        if self.mode == "tabs":
            self.showing = "tree" if self.showing == "tty" else "tty"
        else:
            self.zoomed = False
            self.claude_shown = not self.claude_shown
        self._apply_layout()

    def action_zoom(self) -> None:
        """F3: claude pane full screen (split mode); in tabs mode same as F2."""
        if not self.command:
            return
        if self.mode == "tabs":
            self.action_switch(); return
        self.zoomed = not self.zoomed
        if self.zoomed:
            self.claude_shown = True
        self._apply_layout()

    def action_quit_app(self) -> None:
        if self.command:
            self.query_one(TerminalPane).terminate_child()
        self.exit(0)

    def on_unmount(self) -> None:
        if self.command:
            try:
                self.query_one(TerminalPane).terminate_child()
            except Exception:  # noqa: BLE001
                pass

    def on_key(self, event) -> None:
        if self._exited:
            self.exit(self.query_one(TerminalPane).exit_code or 0)
            return
        if self.command and not self.state.claude_visible and event.key not in ("f1", "f2", "f3", "f10"):
            self.action_switch()   # typing while watching the tree brings claude up

    def on_terminal_pane_exited(self, message: TerminalPane.Exited) -> None:
        self._exited = True
        self.state.phase = "done"
        self.state.add_log("hook", f"claude exited (code {message.code}) — press any key to close", "", "warn")
        self.mount(Static(f" claude exited with code {message.code}. Press any key to close.", id="exit-note"))

    # ---- data ----
    def _poll(self) -> None:
        s = self.state
        if not self.session_id:
            self.session_id = latest_session_id() or ""
            if self.session_id:
                s.session_id = self.session_id
                self._events = JsonlTail(paths.events_file(self.session_id)); self._jev = JevTail(self.session_id)
                self._transcript = TranscriptTail(self.session_id, os.getcwd())
        batch: list[tuple[str, int, object]] = []   # (timestamp, kind, payload) merged in time order
        if self._events:
            batch += [(ev.get("ts", ""), 0, ev) for ev in self._events.read_new()]
        if self._transcript:
            batch += [(line.get("timestamp", ""), 1, (aid, line)) for aid, line in self._transcript.read_new()]
        if self._jev:
            batch += [(row.get("ts", ""), 2, row) for row in self._jev.read_new()]
        for _ts, kind, payload in sorted(batch, key=lambda x: (x[0], x[1])):
            if kind == 0:
                s.apply_event(payload)
            elif kind == 1:
                s.apply_transcript(payload[1], payload[0])
            else:
                s.apply_jev(payload)
        st = read_status(self.session_id) if self.session_id else None
        if st:
            s.apply_status(st)
        s.apply_config(config.load())
        if not s.cwd and self.session_id:
            s.cwd = session_info(self.session_id).get("cwd", "")
        self.query_one(TreeView).refresh_state(s)


def run_app(session_id: str | None, command: list[str] | None, layout: str | None) -> int:
    app = HarnessApp(session_id, command, layout)
    result = app.run()
    return int(result or 0)
