"""Pre-launch menu: resume one of the five most recent Claude Code sessions, or start a new one
(here, or in a fresh git worktree branched from a chosen base). Returns a LaunchPlan; the CLI then
starts the dashboard with claude in the pane."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from . import paths

OPUS, SONNET, JEV, FABLE, DIM, FG, WARN, ERR = "#f0955a", "#7fa7d6", "#7ed99a", "#b9b7d3", "#6b6f80", "#e6e6ea", "#e8c46a", "#e57373"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
TAIL_BYTES = 512 * 1024
HEAD_BYTES = 64 * 1024


# --------------------------------------------------------------------------- session discovery
@dataclass
class SessionInfo:
    id: str
    path: Path
    mtime: float
    title: str = ""
    last_prompt: str = ""
    cwd: str = ""
    branch: str = ""
    entry: str = ""
    live_pid: int | None = None
    live_entry: str = ""

    @property
    def cwd_exists(self) -> bool:
        return bool(self.cwd) and Path(self.cwd).is_dir()

    @property
    def project(self) -> str:
        if not self.cwd:
            return "?"
        parts = self.cwd.split("/.claude/worktrees/")
        if len(parts) == 2:
            return f"{Path(parts[0]).name} ▸ worktree {parts[1].split('/')[0]}"
        return Path(self.cwd).name


def _lines(path: Path, *, head: bool) -> list[dict]:
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if head:
                chunk = f.read(HEAD_BYTES)
            else:
                f.seek(max(0, size - TAIL_BYTES))
                chunk = f.read()
    except OSError:
        return []
    raw = chunk.decode("utf-8", errors="replace").split("\n")
    if not head and size > TAIL_BYTES:
        raw = raw[1:]            # first line is probably cut
    if head and size > HEAD_BYTES:
        raw = raw[:-1]
    out = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _prompt_text(d: dict) -> str:
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        return "" if c.startswith("<") else c
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text" and not str(b.get("text", "")).startswith("<"):
                return b["text"]
    return ""


def read_session(path: Path) -> SessionInfo:
    info = SessionInfo(id=path.stem, path=path, mtime=path.stat().st_mtime)
    custom = ai = agent = first = ""
    for d in _lines(path, head=True):
        if d.get("type") == "user":
            info.cwd = info.cwd or d.get("cwd", "")
            info.entry = info.entry or d.get("entrypoint", "")
            first = first or _prompt_text(d)
    for d in _lines(path, head=False):
        t = d.get("type")
        if t == "custom-title":
            custom = d.get("customTitle") or custom
        elif t == "ai-title":
            ai = d.get("aiTitle") or ai
        elif t == "agent-name":
            agent = d.get("agentName") or agent
        elif t == "last-prompt":
            info.last_prompt = d.get("lastPrompt") or info.last_prompt
        elif t in ("user", "assistant"):
            info.cwd = d.get("cwd") or info.cwd
            info.branch = d.get("gitBranch") or info.branch
            info.entry = info.entry or d.get("entrypoint", "")
    info.title = custom or ai or agent or first.strip().split("\n")[0]
    info.last_prompt = info.last_prompt.strip().replace("\n", " ")
    return info


def live_sessions(claude_dir: Path | None = None) -> dict[str, tuple[int, str]]:
    """sessionId -> (pid, entrypoint) for Claude Code processes that are running now."""
    out: dict[str, tuple[int, str]] = {}
    for f in ((claude_dir or paths.CLAUDE_DIR) / "sessions").glob("*.json"):
        try:
            d = json.loads(f.read_text())
            pid = int(d.get("pid"))
            os.kill(pid, 0)
        except (OSError, ValueError, TypeError):
            continue
        if d.get("sessionId"):
            out[d["sessionId"]] = (pid, d.get("entrypoint", ""))
    return out


def recent_sessions(limit: int = 5, claude_dir: Path | None = None, scan: int = 60) -> list[SessionInfo]:
    """The most recent sessions people actually worked in: top-level transcripts only (subagents are
    nested deeper), headless `claude -p` / SDK runs excluded, and only sessions with a title or prompt."""
    root = (claude_dir or paths.CLAUDE_DIR) / "projects"
    files = sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:scan]
    live = live_sessions(claude_dir)
    out: list[SessionInfo] = []
    for f in files:
        s = read_session(f)
        if s.entry.startswith("sdk") or not (s.title or s.last_prompt):
            continue
        if s.id in live:
            s.live_pid, s.live_entry = live[s.id]
        out.append(s)
        if len(out) >= limit:
            break
    return out


def ago(ts: float) -> str:
    m = int((time.time() - ts) / 60)
    if m < 1:
        return "just now"
    if m < 60:
        return f"{m}m ago"
    if m < 48 * 60:
        return f"{m // 60}h ago"
    return f"{m // 1440}d ago"


# --------------------------------------------------------------------------- git + worktrees
def _git(cwd: str | Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


@dataclass
class RepoInfo:
    root: Path            # top of the current checkout (a worktree or the main one)
    main: Path            # main checkout (worktrees are created under it)
    branch: str
    branches: list[str] = field(default_factory=list)   # local, most recent commit first, + remote default
    default_base: str = ""


def repo_info(cwd: str | Path) -> RepoInfo | None:
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        return None
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    main = Path(common).parent if common.endswith("/.git") else Path(top)
    branch = _git(cwd, "symbolic-ref", "--short", "-q", "HEAD") or _git(cwd, "rev-parse", "--short", "HEAD")
    local = [b for b in _git(cwd, "for-each-ref", "--sort=-committerdate", "--format=%(refname:short)", "refs/heads").splitlines() if b]
    remote_default = _git(cwd, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    trunk = next((b for b in ("master", "main") if b in local), "")
    branches = []
    for b in ([trunk] if trunk else []) + local[:14] + ([remote_default] if remote_default else []):
        if b and b not in branches:
            branches.append(b)
    return RepoInfo(Path(top), main, branch, branches, trunk or branch)


def worktree_path(repo: RepoInfo, name: str) -> Path:
    return repo.main / ".claude" / "worktrees" / name


def validate_name(repo: RepoInfo, name: str) -> str | None:
    if not NAME_RE.match(name):
        return "use letters, digits, '.', '_' or '-' (max 48), starting with a letter or digit"
    if worktree_path(repo, name).exists():
        return f"{worktree_path(repo, name)} already exists"
    if _git(repo.main, "rev-parse", "--verify", "-q", f"refs/heads/worktree-{name}"):
        return f"branch worktree-{name} already exists"
    return None


def create_worktree(repo: RepoInfo, name: str, base: str) -> tuple[Path, list[str]]:
    """git worktree add <main>/.claude/worktrees/<name> -b worktree-<name> <base>; returns (path, notes)."""
    err = validate_name(repo, name)
    if err:
        raise ValueError(err)
    path = worktree_path(repo, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["git", "-C", str(repo.main), "worktree", "add", "-q", str(path), "-b", f"worktree-{name}", base],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError((r.stderr or r.stdout).strip()[:300])
    notes = [f"created {path} on branch worktree-{name} from {base}"]
    # Keep .claude/worktrees out of `git status` (local exclude, never .gitignore).
    probe = ".claude/worktrees/" + name
    if subprocess.run(["git", "-C", str(repo.main), "check-ignore", "-q", probe]).returncode != 0:
        excl = repo.main / ".git" / "info" / "exclude"
        try:
            excl.parent.mkdir(parents=True, exist_ok=True)
            with excl.open("a") as f:
                f.write("\n**/.claude/worktrees/\n")
            notes.append("added **/.claude/worktrees/ to .git/info/exclude")
        except OSError:
            pass
    # JS repos: share the main checkout's node_modules, like the existing Verax worktrees do.
    nm = repo.main / "node_modules"
    if nm.is_dir() and (path / "package.json").exists() and not (path / "node_modules").exists():
        (path / "node_modules").symlink_to(nm)
        notes.append("linked node_modules from the main checkout")
    return path, notes


# --------------------------------------------------------------------------- plan
@dataclass
class LaunchPlan:
    kind: str                       # new | resume | fork
    cwd: str
    session_id: str                 # the id the dashboard should follow
    resume_id: str | None = None
    name: str | None = None
    notes: list[str] = field(default_factory=list)

    def claude_args(self) -> list[str]:
        if self.kind == "resume":
            return ["--resume", self.resume_id or self.session_id]
        args = ["--session-id", self.session_id]
        if self.kind == "fork":
            args = ["--resume", self.resume_id or "", "--fork-session"] + args
        if self.name:
            args += ["--name", self.name]
        return args


# --------------------------------------------------------------------------- UI
CSS = """
Screen { background: #101117; color: #e6e6ea; align: center top; }
#frame { width: 100; max-width: 100%; height: auto; margin: 1 2; }
.title { height: 2; content-align: center middle; text-align: center; }
.hint { color: #6b6f80; height: 1; margin: 1 0 0 0; }
.err { color: #e57373; height: auto; }
OptionList { height: auto; max-height: 30; border: round #3a3d4d; background: #101117; padding: 0 1; }
OptionList:focus { border: round #f0955a; }
OptionList > .option-list--option-highlighted { background: #2e2c44; }
Input { border: round #3a3d4d; background: #101117; }
Input:focus { border: round #f0955a; }
"""


def _title(sub: str) -> Static:
    t = Text(justify="center")
    t.append("CLAUDE CODE AGENT TREE", style=f"bold {FG}"); t.append("  ·  ", style=DIM); t.append(sub, style=f"bold {OPUS}")
    return Static(t, classes="title")


def session_option(s: SessionInfo) -> Option:
    t = Text()
    t.append((s.title or "(untitled)")[:78], style=f"bold {FG}")
    if s.live_pid:
        where = {"claude-desktop": "Desktop", "cli": "a terminal"}.get(s.live_entry, s.live_entry or "another window")
        t.append(f"   ● open in {where}", style=WARN)
    t.append("\n   ")
    meta = [s.project, s.branch, {"claude-desktop": "Desktop", "cli": "CLI"}.get(s.entry, s.entry), ago(s.mtime)]
    t.append(" · ".join(m for m in meta if m), style=DIM)
    if not s.cwd_exists:
        t.append(" · folder no longer exists", style=ERR)
    if s.last_prompt:
        t.append("\n   last: ", style=DIM); t.append(s.last_prompt[:90], style=f"italic {DIM}")
    return Option(t, id=f"s:{s.id}", disabled=not s.cwd_exists)


class HomeScreen(Screen):
    BINDINGS = [Binding("escape,q", "app.quit", "quit")]

    def compose(self) -> ComposeResult:
        app: LauncherApp = self.app  # type: ignore[assignment]
        new = Text(); new.append("＋ New session", style=f"bold {JEV}"); new.append(f"\n   in {app.cwd}", style=DIM)
        opts: list = [Option(new, id="new"), None]
        if app.sessions:
            for s in app.sessions:
                opts += [session_option(s), None]
        else:
            opts.append(Option(Text("no recent sessions found", style=DIM), disabled=True))
        with Vertical(id="frame"):
            yield _title("start or resume")
            yield OptionList(*opts, id="home-list")
            yield Static("↑↓ choose · Enter open · Esc quit   (sessions open elsewhere can be forked)", classes="hint")

    def on_option_list_option_selected(self, msg: OptionList.OptionSelected) -> None:
        app: LauncherApp = self.app  # type: ignore[assignment]
        oid = msg.option.id or ""
        if oid == "new":
            if app.repo:
                app.push_screen(WhereScreen())
            else:
                app.finish(LaunchPlan("new", str(app.cwd), str(uuid.uuid4())))
            return
        s = next(x for x in app.sessions if f"s:{x.id}" == oid)
        if s.live_pid:
            app.push_screen(OpenElsewhereScreen(s))
        else:
            app.finish(LaunchPlan("resume", s.cwd, s.id, resume_id=s.id))


class OpenElsewhereScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "back")]

    def __init__(self, s: SessionInfo):
        super().__init__(); self.s = s

    def compose(self) -> ComposeResult:
        fork = Text(); fork.append("Fork a copy", style=f"bold {JEV}"); fork.append("  (recommended)\n   same history, new session id; the original keeps running untouched", style=DIM)
        anyway = Text(); anyway.append("Resume it anyway", style=f"bold {WARN}"); anyway.append("\n   two windows writing one session can interleave its transcript", style=DIM)
        with Vertical(id="frame"):
            yield _title("session is open elsewhere")
            yield Static(Text(f"“{self.s.title[:80]}” is open (pid {self.s.live_pid}).", style=FG))
            yield OptionList(Option(fork, id="fork"), None, Option(anyway, id="resume"), None, Option(Text("Back", style=DIM), id="back"), id="open-list")
            yield Static("Enter choose · Esc back", classes="hint")

    def on_option_list_option_selected(self, msg: OptionList.OptionSelected) -> None:
        app: LauncherApp = self.app  # type: ignore[assignment]
        if msg.option.id == "fork":
            app.finish(LaunchPlan("fork", self.s.cwd, str(uuid.uuid4()), resume_id=self.s.id))
        elif msg.option.id == "resume":
            app.finish(LaunchPlan("resume", self.s.cwd, self.s.id, resume_id=self.s.id))
        else:
            app.pop_screen()


class WhereScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "back")]

    def compose(self) -> ComposeResult:
        app: LauncherApp = self.app  # type: ignore[assignment]
        r = app.repo
        here = Text(); here.append("Here", style=f"bold {FG}"); here.append(f"\n   {app.cwd} · branch {r.branch}", style=DIM)
        wt = Text(); wt.append("New git worktree", style=f"bold {JEV}"); wt.append(f"\n   isolated checkout under {r.main}/.claude/worktrees/, on its own branch", style=DIM)
        with Vertical(id="frame"):
            yield _title("new session · where")
            yield OptionList(Option(here, id="here"), None, Option(wt, id="worktree"), id="where-list")
            yield Static("Enter choose · Esc back", classes="hint")

    def on_option_list_option_selected(self, msg: OptionList.OptionSelected) -> None:
        app: LauncherApp = self.app  # type: ignore[assignment]
        if msg.option.id == "here":
            app.finish(LaunchPlan("new", str(app.cwd), str(uuid.uuid4())))
        else:
            app.push_screen(BaseScreen())


class BaseScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "back")]

    def compose(self) -> ComposeResult:
        app: LauncherApp = self.app  # type: ignore[assignment]
        r = app.repo
        opts = []
        for b in r.branches:
            t = Text(b, style=f"bold {FG}" if b == r.default_base else FG)
            tags = [x for x, on in (("default", b == r.default_base), ("current", b == r.branch), ("remote", b.startswith("origin/"))) if on]
            if tags:
                t.append("   " + " · ".join(tags), style=DIM)
            opts.append(Option(t, id=f"b:{b}"))
        with Vertical(id="frame"):
            yield _title("new worktree · branch from")
            yield OptionList(*opts, id="base-list")
            yield Static("Enter choose · Esc back", classes="hint")

    def on_mount(self) -> None:
        app: LauncherApp = self.app  # type: ignore[assignment]
        ol = self.query_one(OptionList)
        idx = next((i for i, b in enumerate(app.repo.branches) if b == app.repo.default_base), 0)
        ol.highlighted = idx

    def on_option_list_option_selected(self, msg: OptionList.OptionSelected) -> None:
        self.app.push_screen(NameScreen((msg.option.id or "b:")[2:]))


class NameScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "back")]

    def __init__(self, base: str):
        super().__init__(); self.base = base
        self.suggestion = time.strftime("wt-%m%d-%H%M")

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield _title("new worktree · name")
            yield Static(Text(f"Branching from {self.base}. The worktree gets branch worktree-<name> and the session is named <name>.", style=FG))
            yield Input(value=self.suggestion, placeholder="worktree name", id="name")
            yield Static("", classes="err", id="err")
            yield Static("Enter create · Esc back", classes="hint")

    def on_input_submitted(self, msg: Input.Submitted) -> None:
        app: LauncherApp = self.app  # type: ignore[assignment]
        name = (msg.value or self.suggestion).strip()
        try:
            path, notes = create_worktree(app.repo, name, self.base)
        except ValueError as e:
            self.query_one("#err", Static).update(str(e)); return
        app.finish(LaunchPlan("new", str(path), str(uuid.uuid4()), name=name, notes=notes))


class LauncherApp(App):
    CSS = CSS
    ALLOW_SELECT = False

    def __init__(self, cwd: str | Path, sessions: list[SessionInfo] | None = None):
        super().__init__()
        self.cwd = Path(cwd).resolve()
        self.sessions = recent_sessions() if sessions is None else sessions
        self.repo = repo_info(self.cwd)

    def on_mount(self) -> None:
        self.title = "harness"
        self.push_screen(HomeScreen())

    def finish(self, plan: LaunchPlan) -> None:
        self.exit(plan)


def run_launcher(cwd: str | Path) -> LaunchPlan | None:
    return LauncherApp(cwd).run()
