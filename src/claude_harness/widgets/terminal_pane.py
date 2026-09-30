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

    def compose(self):
        for k, v in self.env.items():
            os.environ[k] = v
        os.environ.setdefault("TERM", "xterm-256color")
        os.environ.setdefault("COLORTERM", "truecolor")
        if self.cwd:
            os.chdir(self.cwd)
        from textual_tty import Terminal
        try:  # bittty spawns with a module-level env dict; make sure the child inherits our full environment
            import bittty.pty.unix as _unix
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
