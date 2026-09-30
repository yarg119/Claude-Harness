"""Fallback layout: claude in the left tmux pane, `harness attach` on the right."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys


def run_tmux(session_id: str, claude_cmd: list[str]) -> int:
    if not shutil.which("tmux"):
        if shutil.which("brew") and input("tmux is not installed. Install with Homebrew? [y/N] ").strip().lower() == "y":
            subprocess.run(["brew", "install", "tmux"], check=False)
        if not shutil.which("tmux"):
            print("tmux not available; use `harness run --layout split` or `harness attach` in a second terminal.")
            return 1
    name = f"harness-{session_id[:8]}"
    left = " ".join(shlex.quote(c) for c in claude_cmd)
    right = f"{shlex.quote(sys.argv[0])} attach {shlex.quote(session_id)}"
    env = {**os.environ, "HARNESS_SESSION_ID": session_id}
    subprocess.run(["tmux", "new-session", "-d", "-s", name, "-x", "220", "-y", "50", left], env=env, check=True)
    subprocess.run(["tmux", "split-window", "-h", "-t", name, "-p", "40", right], env=env, check=True)
    subprocess.run(["tmux", "select-pane", "-t", f"{name}:0.0"], check=False)
    return subprocess.call(["tmux", "attach", "-t", name])
