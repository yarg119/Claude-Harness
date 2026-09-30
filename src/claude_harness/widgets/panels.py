"""Dashboard panels laid out like the agent-tree mockup (designed for 90x46, scales up)."""
from __future__ import annotations

import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import RichLog, Sparkline, Static

from ..state import AGENT_KINDS, SessionState

OPUS, SONNET, JEV, FABLE = "#f0955a", "#7fa7d6", "#7ed99a", "#b9b7d3"
DIM, FG, WARN, ERR, LINE = "#6b6f80", "#e6e6ea", "#e8c46a", "#e57373", "#3a3d4d"
SPIN = "|/-\\"
EFFORT_LEVELS = {"low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5, "ultracode": 4}
AGENT_ROLE = {"worker": "edits + tests", "explorer": "read code", "researcher": "look up docs", "reviewer": "review", "other": "task"}


def spin() -> str:
    return SPIN[int(time.time() * 4) % 4]


def effort_bar(level: str, color: str) -> Text:
    n = EFFORT_LEVELS.get((level or "").lower(), 0)
    t = Text("effort ")
    t.append("■" * n, style=color); t.append("□" * (5 - n), style=DIM); t.append(f" {level or '?'}", style=f"bold {color}")
    return t


def ratio_bar(sharp: float, width: int = 10) -> Text:
    n = round(sharp * width)
    t = Text(); t.append("█" * n, style=JEV); t.append("▒" * (width - n), style=OPUS)
    return t


def fmt_tokens(n: int) -> str:
    return f"{n/1000:.0f}k" if n >= 1000 else str(n)


def fmt_ctx(size: int) -> str:
    if size >= 1_000_000:
        return f"{size/1_000_000:.0f}M"
    return f"{size // 1000}k" if size else "200k"


def clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: max(n - 1, 0)] + "…"


class Panel(Static):
    DEFAULT_CSS = "Panel { height: auto; padding: 0; }"

    def render_state(self, s: SessionState) -> Text:  # pragma: no cover - overridden
        return Text("")

    def refresh_state(self, s: SessionState) -> None:
        self.update(self.render_state(s))


class Header(Panel):
    DEFAULT_CSS = "Header { height: 2; text-align: center; }"

    def render_state(self, s: SessionState) -> Text:
        t = Text(justify="center")
        t.append("CLAUDE CODE AGENT TREE", style=f"bold {FG}"); t.append("  ·  ", style=DIM)
        t.append("OPUS 5.5 ARCHITECT", style=f"bold {OPUS}"); t.append("  ·  ", style=DIM)
        t.append("SONNET 5.5 SWARM", style=f"bold {SONNET}"); t.append("  ·  ", style=DIM)
        t.append("FABLE 5.1 ON CALL", style=f"bold {FABLE}"); t.append("\n")
        for color, label in ((OPUS, f"opus 5.5 · {s.effort or 'high'}"), (SONNET, f"sonnet 5.5 · {s.subagent_effort}"),
                             (JEV, "jev · forks" if s.jev_enabled else "jev · off"), (FABLE, "fable 5.1 · advisor" if s.advisor.model else "fable · off")):
            t.append(" ■ ", style=color); t.append(label + " ", style=DIM)
        return t


class AdvisorPanel(Panel):
    DEFAULT_CSS = "AdvisorPanel { border: round #4a4866; width: 28%; min-width: 26; max-width: 34; height: 100%; }"

    def render_state(self, s: SessionState) -> Text:
        a = s.advisor; t = Text(); on = bool(a.model)
        t.append("  Fable · on call\n", style=f"bold {FABLE}" if on else f"bold {DIM}")
        t.append(f"  /advisor {'fable' if on else 'off'}\n\n", style=DIM if on else ERR)
        t.append(" Opus calls it:\n\n", style=DIM)
        for kind, desc in (("before a plan", ("reads full session", "every tool call")),
                           ("error repeats", ("never writes code", "Opus applies advice")),
                           ("before done", ("pre-flight contract", "zero regression check"))):
            hot = a.last_kind == kind
            t.append(" ◆ " if hot else " · ", style=FABLE if hot else DIM)
            t.append(f"{kind:<19}\n", style=f"bold {FG} on #2e2c44" if hot else FG)
            for line in desc:
                t.append(f"   {line}\n", style=DIM)
            if hot and a.last_applied:
                t.append("   last advice:\n", style=DIM)
                import textwrap
                for chunk in textwrap.wrap(a.last_applied, 19)[:2]:
                    t.append(f"   » {chunk}\n", style=FG)
            t.append("\n")
        t.append(" calls", style=DIM); t.append(f"{a.calls:>15}\n", style=f"bold {FG}")
        t.append(" tokens read", style=DIM); t.append(f"{fmt_tokens(a.tokens_read):>9}\n", style=f"bold {FG}")
        t.append(" last", style=DIM); t.append(f"{(a.last_status or '—'):>16}\n\n", style=FABLE if a.last_status == "Reviewed" else WARN)
        if a.in_progress:
            t.append(f" advising {spin()}", style=f"bold {FABLE}")
        elif a.calls == 0:
            t.append(" stands by idle\n until called", style=DIM)
        else:
            t.append(" silent on routine", style=DIM)
        return t


class MainSession(Panel):
    DEFAULT_CSS = "MainSession { border: round #f0955a; width: 60%; min-width: 38; max-width: 70; text-align: center; } MainSession.waiting { border: round #e8c46a; }"

    def render_state(self, s: SessionState) -> Text:
        self.set_class(s.phase == "awaiting" and s.embedded, "waiting")
        t = Text(justify="center")
        t.append(f"{s.model.title()} · {s.effort or 'high'}\n", style=f"bold {OPUS}")
        t.append("main session\n", style=FG)
        t.append_text(effort_bar(s.effort or "high", OPUS)); t.append("\n")
        if s.phase == "awaiting" and s.embedded:
            t.append("claude is waiting for you → F2", style=f"bold {WARN}")
        else:
            phase = {"idle": "idle", "thinking": f"thinking {spin()}", "tool": f"tool: {clip(s.current_tool, 18)}", "awaiting": "waiting", "done": "exited"}.get(s.phase, s.phase)
            t.append(f"plans + decides · {fmt_ctx(s.ctx_size)} · ctx {s.ctx_pct:.0f}%\n", style=DIM)
            t.append(clip(phase, 34), style=DIM)
        return t


class JevPanel(Panel):
    DEFAULT_CSS = "JevPanel { border: round #7ed99a; width: 76%; min-width: 48; max-width: 90; }"

    def render_state(self, s: SessionState) -> Text:
        t = Text()
        t.append(" JEV · fork layer", style=f"bold {JEV}")
        total = f"{s.jev_forks_total:,}" if s.jev_enabled else "off"
        inner = max((self.size.width or 48) - 2, 46)
        t.append(f"{'forks':>{max(1, inner - 17 - len(total) - 1)}} ", style=DIM); t.append(total + "\n", style=f"bold {FG}")
        for name, label in (("route", "which worker"), ("tool_risk", "which tool"), ("retry_or_stop", "retry or stop")):
            f = s.jev[name]
            t.append(f"  {label:<14}", style=FG); t.append_text(ratio_bar(f.sharp_ratio, max(10, inner - 36)))
            if f.total:
                t.append(f" {f.last_p:.2f} ", style=f"bold {FG}"); t.append(f"{f.last_verdict:<5}", style=JEV if f.last_verdict == "sharp" else OPUS)
                t.append(f" {clip(f.last_choice, max(7, inner - 44))}", style=DIM)
            else:
                t.append(" —", style=DIM)
            t.append("\n")
        t.append("  sharp → runs in code", style=JEV); t.append("     split → Opus", style=OPUS)
        return t


class Dispatcher(Static):
    DEFAULT_CSS = "Dispatcher { border: round #7fa7d6; width: 76%; min-width: 48; max-width: 90; height: 4; } Dispatcher > Static { height: 1; } Dispatcher > Sparkline { height: 1; margin: 0 1; }"

    def compose(self) -> ComposeResult:
        yield Static(id="disp-text")
        yield Sparkline([0.0] * 30, summary_function=max, id="disp-spark")

    def refresh_state(self, s: SessionState) -> None:
        n = len(s.active_agents)
        tps = s.tokens_per_s[-1] if s.tokens_per_s else 0
        t = Text(); t.append(" SONNET 5.5 · DISPATCHER", style=f"bold {SONNET}")
        t.append(f"   {s.subagent_effort[:3]} · {n}x swarm · {tps:.0f} t/s", style=DIM)
        self.query_one("#disp-text", Static).update(t)
        self.query_one("#disp-spark", Sparkline).data = list(s.tokens_per_s)


class Connector(Static):
    DEFAULT_CSS = "Connector { height: 1; width: 100%; text-align: center; color: #6b6f80; }"

    def __init__(self, glyph: str = "▼"):
        super().__init__(glyph)


class AgentBox(Panel):
    DEFAULT_CSS = "AgentBox { border: round #3a3d4d; width: 1fr; min-width: 21; max-width: 34; height: 7; text-align: center; } AgentBox.running { border: round #7fa7d6; } AgentBox.done { border: round #4c5a6e; }"

    def __init__(self, kind: str):
        super().__init__(); self.kind = kind

    def render_state(self, s: SessionState) -> Text:
        a = s.agent_for_kind(self.kind)
        running = a is not None and a.status == "running"
        self.set_class(running, "running"); self.set_class(a is not None and not running, "done")
        t = Text(justify="center")
        t.append(f"{self.kind}\n", style=f"bold {FG}"); t.append("Sonnet 5.5 · medium\n", style=SONNET)
        t.append(AGENT_ROLE.get(self.kind, "task") + "\n", style=FG)
        if running:
            t.append(f"[{spin()} running]\n", style=f"bold {SONNET}"); t.append(clip(a.current_tool or "…", 19), style=DIM)
        elif a is not None:
            t.append(f"done · {fmt_tokens(a.out_tokens)} tok\n", style=DIM); t.append(clip(a.last_text or a.desc, 19), style=DIM)
        else:
            t.append("[idle]", style=DIM)
        return t


class ReturnBox(Panel):
    DEFAULT_CSS = "ReturnBox { border: round #f0955a; width: 60%; min-width: 38; max-width: 70; text-align: center; } ReturnBox.dim { border: round #3a3d4d; }"

    def render_state(self, s: SessionState) -> Text:
        back = bool(s.agents) and not s.active_agents and s.phase in ("thinking", "tool")
        self.set_class(not back, "dim")
        t = Text(justify="center")
        t.append(f"back to main session · {s.effort or 'high'}\n", style=f"bold {OPUS}" if back else DIM)
        t.append("review + verify", style=FG if back else DIM)
        return t


class SessionLog(RichLog):
    DEFAULT_CSS = "SessionLog { border: round #3a3d4d; height: 1fr; min-height: 7; border-title-color: #6b6f80; scrollbar-size: 0 0; }"
    ACTOR_STYLE = {"opus": OPUS, "sonnet": SONNET, "fable": FABLE, "jev": JEV, "hook": DIM, "you": FG, "codex": WARN, "haiku": SONNET}

    def __init__(self):
        super().__init__(markup=False, wrap=False, max_lines=400, min_width=20)
        self.border_title = "session log"; self._seen = 0

    def refresh_state(self, s: SessionState) -> None:
        lines = list(s.log)
        if len(lines) < self._seen:
            self.clear(); self._seen = 0
        width = max(self.size.width - 2, 40)
        for line in lines[self._seen:]:
            actor = (line.actor.split()[0] if line.actor else "hook")[:6]
            right = clip(line.right, 24)
            msg_w = max(width - (8 + 2 + 6 + 1) - (len(right) + 3 if right else 0), 10)
            t = Text(); t.append(f"{line.ts}  ", style=DIM)
            t.append(f"{actor:<6} ", style=f"bold {self.ACTOR_STYLE.get(actor, FG)}")
            t.append(f"{clip(line.text, msg_w):<{msg_w}}", style={"warn": WARN, "error": ERR}.get(line.level, FG))
            if right:
                t.append("   " + right, style=DIM)
            self.write(t)
        self._seen = len(lines)


class CommandBar(Panel):
    DEFAULT_CSS = "CommandBar { height: 1; padding: 0 1; }"

    def render_state(self, s: SessionState) -> Text:
        t = Text()
        cwd = ("~/" + s.cwd.split("/")[-1]) if s.cwd else "~"
        t.append(f"{cwd} $ ", style=DIM)
        t.append(clip(s.launch_cmd or "claude", max(self.size.width - len(cwd) - 24, 20)), style=FG)
        if s.embedded:
            hint = "claude is waiting → F2" if s.phase == "awaiting" else ("F2 hide claude · F3 zoom" if s.claude_visible else "F2 → claude pane")
            t.append(f"   {hint}", style=f"bold {WARN}" if s.phase == "awaiting" else DIM)
        return t


class StatusBar(Panel):
    DEFAULT_CSS = "StatusBar { height: 1; padding: 0 1; background: #16171e; }"

    def render_state(self, s: SessionState) -> Text:
        t = Text(); w = self.size.width or 90

        sep = "  " if w >= 110 else " "

        def kv(k: str, v: str, color: str) -> None:
            t.append(f"{k}: ", style=DIM); t.append("[", style=DIM); t.append(v, style=color); t.append("]" + sep, style=DIM)
        kv("effort", f"{s.effort or 'high'}/{s.subagent_effort[:3] if w < 110 else s.subagent_effort}", OPUS)
        kv("subagents" if w >= 110 else "agents", f"{len(s.active_agents)}/{max(len(s.agents), 3)}", SONNET)
        kv("fable", "advising" if s.advisor.in_progress else ("on call" if s.advisor.model else "off"), FABLE)
        kv("jev", (f"{s.jev_forks_total:,} forks" if w >= 100 else f"{s.jev_forks_total:,}") if s.jev_enabled else "off", JEV)
        kv("codex", "on" if s.codex_enabled else "off", WARN if s.codex_enabled else DIM)
        t.append(f"ctx {s.ctx_pct:.0f}% ${s.cost:.2f}", style=DIM)
        if s.rate_5h and w >= 110:
            t.append(f"  5h {s.rate_5h:.0f}%", style=WARN if s.rate_5h > 85 else DIM)
        if w >= 130:
            t.append("   F1 help  F2 view  F3 zoom  F10 quit", style=DIM)
        return t


class TreeView(Vertical):
    """The whole agent tree (everything except the terminal pane)."""
    DEFAULT_CSS = """
    TreeView { height: 100%; }
    #tree-body { height: auto; }
    #center { width: 1fr; height: auto; align: center top; }
    #agents { width: 100%; max-width: 104; height: 7; align: center top; }
    """

    def compose(self) -> ComposeResult:
        yield Header(id="header")
        with Horizontal(id="tree-body"):
            yield AdvisorPanel(id="advisor")
            with Vertical(id="center"):
                yield MainSession(id="main")
                yield Connector()
                yield JevPanel(id="jev")
                yield Connector()
                yield Dispatcher(id="dispatcher")
                yield Connector("▼      ▼      ▼")
                with Horizontal(id="agents"):
                    for k in AGENT_KINDS:
                        yield AgentBox(k)
                yield Connector()
                yield ReturnBox(id="return")
        yield SessionLog()
        yield CommandBar(id="cmdbar")
        yield StatusBar(id="status")

    def on_resize(self) -> None:
        self.query_one(AdvisorPanel).display = self.size.width >= 90

    def refresh_state(self, s: SessionState) -> None:
        for w in self.query(Panel):
            w.refresh_state(s)
        self.query_one(Dispatcher).refresh_state(s)
        self.query_one(SessionLog).refresh_state(s)
