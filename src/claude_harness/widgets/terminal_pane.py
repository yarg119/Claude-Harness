"""Adapter around textual-tty's Terminal so the emulator can be swapped (e.g. ghostty-textual) later."""
from __future__ import annotations

import os

from textual.message import Message
from textual.widget import Widget


class TerminalPane(Widget):
    DEFAULT_CSS = "TerminalPane { width: 1fr; height: 100%; } TerminalPane > * { width: 100%; height: 100%; }"

    class Exited(Message):
        def __init__(self, code: int) -> None:
            self.code = code; super().__init__()

    def __init__(self, command: list[str], env: dict[str, str] | None = None, cwd: str | None = None,
                 id: str | None = None, classes: str | None = None):
        super().__init__(id=id, classes=classes)
        self.command = command
        self.env = env or {}
        self.cwd = cwd
        self.exit_code: int | None = None

    HOTKEYS = {"f1": "help", "f2": "switch", "f3": "zoom", "f10": "quit_app"}

    # Markers a parent Claude Code session exports; inherited by the child they make it think it is
    # nested (e.g. "Transcript saving is off — inherited CLAUDE_CODE_CHILD_SESSION").
    NESTING_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID",
                       "CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_MESSAGING_SOCKET",
                       "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_BRIDGE_SESSION_ID")

    def compose(self):
        for k in self.NESTING_MARKERS:
            os.environ.pop(k, None)
        for k, v in self.env.items():
            os.environ[k] = v
        os.environ.setdefault("TERM", "xterm-256color")
        os.environ.setdefault("COLORTERM", "truecolor")
        if self.cwd:
            os.chdir(self.cwd)
        from textual_tty import Terminal
        from textual_tty.widget import TerminalChrome

        hotkeys = self.HOTKEYS

        class HarnessChrome(TerminalChrome):
            """bittty 0.1.x reports mouse tracking via on_mouse_capture; textual-tty 0.4 only
            implements the older on_mouse_mode, so the widget never learned the child wanted the
            mouse and dropped every wheel event. Bridge the two so scrolling reaches claude."""

            def on_mouse_capture(self, mode: str) -> None:
                self.widget.mouse_mode = mode

        class HarnessTerminal(Terminal):
            """Terminal that hands the dashboard hotkeys back to the app instead of the child."""

            CHROME = HarnessChrome

            # --- mouse: keep press/drag/release paired so claude's own selection ends --- #
            # Without capture, a drag that leaves the pane never delivers the release; claude then
            # treats every later move as "button held" and its selection grows across the screen.
            def _input_mouse(self, event, button, event_type) -> None:  # type: ignore[override]
                w, h = max(self.size.width, 1), max(self.size.height, 1)
                x = min(max(event.offset.x, 0), w - 1)
                y = min(max(event.offset.y, 0), h - 1)
                mods = {m for m, on in (("shift", event.shift), ("meta", event.meta), ("ctrl", event.ctrl)) if on}
                self.board.display.input_mouse(x + 1, y + 1, button, event_type, mods)

            _buttons_down = 0

            def on_mouse_down(self, event) -> None:  # type: ignore[override]
                if self.mouse_mode != "off":
                    self.capture_mouse()
                self._buttons_down += 1
                super().on_mouse_down(event)

            def on_mouse_up(self, event) -> None:  # type: ignore[override]
                if self._buttons_down > 0:          # Textual can deliver the up twice while captured
                    self._buttons_down -= 1
                    super().on_mouse_up(event)
                if self._buttons_down == 0 and self.app.mouse_captured is self:
                    self.release_mouse()

            def on_key(self, event) -> None:  # type: ignore[override]
                action = hotkeys.get(event.key)
                if action:
                    event.stop(); event.prevent_default()
                    self.app.call_later(getattr(self.app, f"action_{action}"))
                    return
                super().on_key(event)

        Terminal = HarnessTerminal
        try:  # bittty spawns with a module-level env dict; make sure the child inherits our full environment
            import bittty.pty.unix as _unix
            for k in self.NESTING_MARKERS:
                _unix.UNIX_ENV.pop(k, None)
            _unix.UNIX_ENV.update(os.environ)
        except Exception:  # noqa: BLE001
            pass
        # bittty passes a str as a single argv element, so always hand it the list.
        yield Terminal(command=list(self.command), id="tty")

    def on_mount(self) -> None:
        self.query_one("#tty").focus()

    def focus_tty(self) -> None:
        try:
            self.query_one("#tty").focus()
        except Exception:  # noqa: BLE001
            pass

    def on_terminal_process_exited(self, message) -> None:
        self.exit_code = message.exit_code
        self.post_message(self.Exited(message.exit_code))

    def child_pid(self) -> int | None:
        try:
            proc = self.query_one("#tty").board.process
            return proc.pid if proc is not None and proc.poll() is None else None
        except Exception:  # noqa: BLE001
            return None

    def terminate_child(self, grace: float = 1.5) -> None:
        """Hang up the child (its own process group), then kill it if it lingers."""
        import signal
        import time
        pid = self.child_pid()
        if pid is None:
            return
        for sig in (signal.SIGHUP, signal.SIGTERM):
            try:
                os.killpg(os.getpgid(pid), sig)
            except ProcessLookupError:
                return
            except OSError:
                pass
            t0 = time.time()
            while time.time() - t0 < grace:
                if self.child_pid() is None:
                    return
                time.sleep(0.05)
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            pass

    def on_unmount(self) -> None:
        self.terminate_child()
