"""`harness` command line: run | attach | install | uninstall | doctor | init | codex | jev | jev-hook | config | events."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from . import __version__, config, paths


def _print_log(lines) -> None:
    for line in lines:
        print(line)


def cmd_install(a: argparse.Namespace) -> int:
    from . import installer
    _print_log(installer.install(with_codex=a.with_codex, remove_pm=not a.keep_puppetmaster, dry=a.dry_run, force=a.force))
    return 0


def cmd_uninstall(a: argparse.Namespace) -> int:
    from . import installer
    _print_log(installer.uninstall(dry=a.dry_run))
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    from . import doctor
    text, rc = doctor.report(live=not a.no_live)
    print(text)
    return rc


def cmd_init(a: argparse.Namespace) -> int:
    from . import installer
    _print_log(installer.init_project(Path(a.dir)))
    return 0


def cmd_codex(a: argparse.Namespace) -> int:
    from . import installer
    if a.state is None:
        print("codex:", "on" if config.load().get("codex") else "off")
        return 0
    _print_log(installer.set_codex(a.state == "on"))
    return 0


def cmd_jev(a: argparse.Namespace) -> int:
    from . import installer
    if a.state is None:
        print("jev:", "on" if config.load().get("jev") else "off", f"(threshold {config.load().get('jev_threshold')})")
        return 0
    if a.state == "test":
        from . import jev
        for row in jev.test_forks():
            print(json.dumps(row))
        return 0
    _print_log(installer.set_jev(a.state == "on"))
    return 0


def cmd_jev_hook(a: argparse.Namespace) -> int:
    # Called by hook scripts with the hook's stdin JSON. Must never fail loudly.
    try:
        from . import jev
        raw = sys.stdin.read()
        out = jev.hook(a.fork, json.loads(raw) if raw.strip() else {})
        if out:
            sys.stdout.write(json.dumps(out) + "\n")
    except Exception as e:  # noqa: BLE001
        if os.environ.get("HARNESS_DEBUG"):
            sys.stderr.write(f"jev-hook error: {e}\n")
    return 0


def cmd_config(a: argparse.Namespace) -> int:
    cfg = config.load()
    if a.key is None:
        print(json.dumps(cfg, indent=2))
        return 0
    if a.value is None:
        v = cfg.get(a.key)
        print(json.dumps(v) if not isinstance(v, str) else v)
        return 0
    val: object = a.value
    if a.value in ("true", "false"):
        val = a.value == "true"
    else:
        try:
            val = float(a.value) if "." in a.value else int(a.value)
        except ValueError:
            pass
    config.set_value(a.key, val)
    print(f"{a.key} = {val}")
    return 0


def cmd_events(a: argparse.Namespace) -> int:
    from .sources.events import latest_session_id, tail_events
    sid = a.session or latest_session_id()
    if not sid:
        print("no sessions recorded yet")
        return 1
    for ev in tail_events(sid, follow=a.follow):
        print(json.dumps(ev))
    return 0


def cmd_attach(a: argparse.Namespace) -> int:
    from .app import run_app
    return run_app(session_id=a.session, command=None, layout=a.layout)


def cmd_run(a: argparse.Namespace) -> int:
    from .app import run_app
    sid = str(uuid.uuid4())
    cfg = config.load()
    cmd = ["claude", "--session-id", sid]
    if not a.no_advisor:
        cmd += ["--advisor", a.advisor]
    model = a.model or ("opus[1m]" if (a.one_million or cfg.get("one_million_context")) else "opus")
    cmd += ["--model", model, "--effort", a.effort]
    if a.name:
        cmd += ["--name", a.name]
    cmd += a.claude_args
    if a.print_cmd:
        print(" ".join(cmd))
        return 0
    if a.layout == "tmux":
        from .tmux import run_tmux
        return run_tmux(sid, cmd)
    return run_app(session_id=sid, command=cmd, layout=a.layout)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness", description="Agent-tree harness and TUI for Claude Code and Codex")
    p.add_argument("--version", action="version", version=f"harness {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("run", help="launch claude inside the dashboard (embedded PTY)")
    s.add_argument("--layout", choices=["auto", "split", "tabs", "tmux"], default=None)
    s.add_argument("--advisor", default="fable"); s.add_argument("--no-advisor", action="store_true")
    s.add_argument("--model", default=None); s.add_argument("--effort", default="high")
    s.add_argument("--1m", dest="one_million", action="store_true", help="use opus[1m]")
    s.add_argument("--name", default=None); s.add_argument("--print-cmd", action="store_true")
    s.add_argument("claude_args", nargs=argparse.REMAINDER, help="extra args passed to claude (after --)")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("attach", help="dashboard only, watching an existing session")
    s.add_argument("session", nargs="?", default=None, help="session id (default: latest)")
    s.add_argument("--layout", choices=["auto", "split", "tabs"], default=None)
    s.set_defaults(fn=cmd_attach)

    s = sub.add_parser("install", help="install into ~/.claude (and ~/.codex with --with-codex)")
    s.add_argument("--with-codex", action="store_true"); s.add_argument("--keep-puppetmaster", action="store_true")
    s.add_argument("--dry-run", action="store_true"); s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("uninstall"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_uninstall)
    s = sub.add_parser("doctor"); s.add_argument("--no-live", action="store_true", help="skip network checks"); s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("init", help="copy the project template into a repo"); s.add_argument("dir", nargs="?", default="."); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("codex"); s.add_argument("state", nargs="?", choices=["on", "off"]); s.set_defaults(fn=cmd_codex)
    s = sub.add_parser("jev"); s.add_argument("state", nargs="?", choices=["on", "off", "test"]); s.set_defaults(fn=cmd_jev)
    s = sub.add_parser("jev-hook", help="(internal) decide a fork from hook stdin"); s.add_argument("fork", choices=["route", "tool_risk", "retry_or_stop"]); s.set_defaults(fn=cmd_jev_hook)
    s = sub.add_parser("config"); s.add_argument("key", nargs="?"); s.add_argument("value", nargs="?"); s.set_defaults(fn=cmd_config)
    s = sub.add_parser("events", help="print a session's event stream"); s.add_argument("session", nargs="?"); s.add_argument("-f", "--follow", action="store_true"); s.set_defaults(fn=cmd_events)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "run" and args.claude_args and args.claude_args[0] == "--":
        args.claude_args = args.claude_args[1:]
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
