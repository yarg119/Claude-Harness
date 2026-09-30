"""Dashboard panels. Each panel is a Static that re-renders from a SessionState snapshot."""
from __future__ import annotations

import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import RichLog, Sparkline, Static

from ..state import AGENT_KINDS, SessionState

OPUS, SONNET, JEV, FABLE, DIM, FG, WARN, ERR = "#f0955a", "#7fa7d6", "#7ed99a", "#b9b7d3", "#6b6f80", "#e6e6ea", "#e8c46a", "#e57373"
SPIN = "|/-\\"
EFFORT_LEVELS = {"low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5, "ultracode": 4}
AGENT_ROLE = {"worker": "edits + tests", "explorer": "read code", "researcher": "look up docs", "reviewer": "adversarial review", "other": "task"}


def effort_bar(level: str, color: str) -> Text:
    n = EFFORT_LEVELS.get((level or "").lower(), 0)
    t = Text("effort ")
    t.append("■" * n, style=color); t.append("□" * (5 - n), style=DIM); t.append(f" {level or '?'}", style=f"bold {color}")
    return t


def ratio_bar(sharp: float, width: int = 14) -> Text:
    n = round(sharp * width)
    t = Text(); t.append("█" * n, style=JEV); t.append("▒" * (width - n), style=OPUS)
    return t


def fmt_tokens(n: int) -> str:
    return f"{n/1000:.0f}k" if n >= 1000 else str(n)


class Panel(Static):
    DEFAULT_CSS = "Panel { border: round #3a3d4d; padding: 0 1; height: auto; }"

    def render_state(self, s: SessionState) -> Text:  # pragma: no cover - overridden
        return Text("")

    def refresh_state(self, s: SessionState) -> None:
        self.update(self.render_state(s))


class Header(Panel):
    DEFAULT_CSS = "Header { border: none; height: 3; content-align: center middle; text-align: center; }"

    def render_state(self, s: SessionState) -> Text:
        t = Text(justify="center")
        t.append("CLAUDE CODE AGENT TREE", style=f"bold {FG}"); t.append("  ·  ", style=DIM)
        t.append("OPUS 5.5 ARCHITECT", style=f"bold {OPUS}"); t.append("  ·  ", style=DIM)
        t.append("SONNET 5.5 SWARM", style=f"bold {SONNET}"); t.append("  ·  ", style=DIM)
        t.append("FABLE 5.1 ON CALL", style=f"bold {FABLE}"); t.append("\n")
        for color, label in ((OPUS, f"opus 5.5 · {s.effort or 'high'}"), (SONNET, f"sonnet 5.5 · swarm"), (JEV, "jev · forks" if s.jev_enabled else "jev · off"), (FABLE, "fable 5.1 · advisor")):
            t.append("  ■ ", style=color); t.append(label, style=DIM)
        return t


class AdvisorPanel(Panel):
    DEFAULT_CSS = "AdvisorPanel { border: round #4a4866; width: 30; height: 100%; }"

    def render_state(self, s: SessionState) -> Text:
        a = s.advisor; t = Text()
        on = bool(a.model)
        t.append("Fable · on call\n", style=f"bold {FABLE}" if on else f"bold {DIM}")
        t.append(f"/advisor {a.model.replace('claude-', '') if on else 'off'}\n\n", style=DIM if on else ERR)
        t.append("Opus usually calls it:\n", style=DIM)
        for kind, desc in (("before a plan", "reads full session\nevery tool call"), ("error repeats", "never writes code\nOpus applies advice"), ("before done", "pre-flight contract\nzero regression check")):
            active = a.last_kind == kind and (a.in_progress or time.time() - s.started < 1e9)
            t.append(("◆ " if a.last_kind == kind else "· "), style=FABLE if a.last_kind == kind else DIM)
            t.append(kind + "\n", style=f"bold {FG} on #2e2c44" if a.last_kind == kind else FG)
            for line in desc.split("\n"):
                t.append("  " + line + "\n", style=DIM)
            if a.last_kind == kind and a.last_applied:
                t.append("  last advice:\n", style=DIM); t.append("  » " + a.last_applied[:40] + "\n", style=FG)
            t.append("\n")
        t.append("calls", style=DIM); t.append(f"{a.calls:>16}\n", style=f"bold {FG}")
        t.append("tokens read", style=DIM); t.append(f"{fmt_tokens(a.tokens_read):>10}\n", style=f"bold {FG}")
        t.append("last", style=DIM); t.append(f"{(a.last_status or '—'):>17}\n\n", style=FABLE if a.last_status == "Reviewed" else WARN)
        if a.in_progress:
            t.append("advising " + SPIN[int(time.time() * 4) % 4], style=f"bold {FABLE}")
        elif a.calls == 0:
            t.append("stands by idle\nuntil called", style=DIM)
        else:
            t.append("silent on routine", style=DIM)
        return t


class MainSession(Panel):
    DEFAULT_CSS = "MainSession { border: round #f0955a; content-align: center middle; text-align: center; }"

    def render_state(self, s: SessionState) -> Text:
        t = Text(justify="center")
        t.append(f"{s.model.title()} · {s.effort or 'high'}\n", style=f"bold {OPUS}")
        t.append("main session\n", style=FG)
        t.append_text(effort_bar(s.effort or "high", OPUS)); t.append("\n")
        ctx = f"{s.ctx_size // 1000}k" if s.ctx_size else "200k"
        phase = {"idle": "idle", "thinking": "thinking " + SPIN[int(time.time() * 4) % 4], "tool": f"tool: {s.current_tool}", "awaiting": "waiting for you", "done": "exited"}.get(s.phase, s.phase)
        t.append(f"plans + decides · {ctx} · ctx {s.ctx_pct:.0f}% · {phase}", style=DIM)
        return t


class JevPanel(Panel):
    DEFAULT_CSS = "JevPanel { border: round #7ed99a; }"

    def render_state(self, s: SessionState) -> Text:
        t = Text()
        t.append("JEV · fork layer", style=f"bold {JEV}")
        t.append(f"{'forks':>26} ", style=DIM); t.append(f"{s.jev_forks_total:,}\n" if s.jev_enabled else "off\n", style=f"bold {FG}")
        for name, label in (("route", "which worker"), ("tool_risk", "which tool"), ("retry_or_stop", "retry or stop")):
            f = s.jev[name]
            t.append(f"  {label:<14}", style=FG); t.append_text(ratio_bar(f.sharp_ratio))
            if f.total:
                t.append(f"  {f.last_p:.2f} ", style=f"bold {FG}"); t.append(f.last_verdict, style=JEV if f.last_verdict == "sharp" else OPUS)
                t.append(f" {f.last_choice}", style=DIM)
            else:
                t.append("  —", style=DIM)
            t.append("\n")
        t.append("  sharp → runs in code", style=JEV); t.append("      split → Opus", style=OPUS)
        return t


class Dispatcher(Static):
    DEFAULT_CSS = "Dispatcher { border: round #7fa7d6; height: 5; padding: 0 1; } Dispatcher Sparkline { width: 24; height: 1; } Dispatcher Static { width: 1fr; height: 1; }"

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static(id="disp-text")
            yield Sparkline([0.0] * 30, summary_function=max, id="disp-spark")

    def refresh_state(self, s: SessionState) -> None:
        n = len(s.active_agents)
        tps = s.tokens_per_s[-1] if s.tokens_per_s else 0
        t = Text(); t.append("SONNET 5.5 · DISPATCHER ", style=f"bold {SONNET}")
        t.append(f"{s.subagent_effort[:3]} · {n}x swarm · {tps:.0f} t/s", style=DIM)
        self.query_one("#disp-text", Static).update(t)
        self.query_one("#disp-spark", Sparkline).data = list(s.tokens_per_s)


class AgentBox(Panel):
    DEFAULT_CSS = "AgentBox { border: round #3a3d4d; width: 1fr; height: 8; content-align: center middle; text-align: center; } AgentBox.running { border: round #7fa7d6; }"

    def __init__(self, kind: str):
        super().__init__(); self.kind = kind

    def render_state(self, s: SessionState) -> Text:
        a = s.agent_for_kind(self.kind)
        running = a is not None and a.status == "running"
        self.set_class(running, "running")
        t = Text(justify="center")
        t.append(f"{self.kind}\n", style=f"bold {FG}"); t.append("Sonnet 5.5 · medium\n\n", style=SONNET)
        t.append(AGENT_ROLE.get(self.kind, "task") + "\n", style=FG)
        if running:
            t.append(f"[{SPIN[int(time.time() * 4) % 4]} running] {a.current_tool}\n", style=f"bold {SONNET}")
            t.append(fmt_tokens(a.out_tokens) + " tok", style=DIM)
        elif a is not None:
            t.append(f"done · {fmt_tokens(a.out_tokens)} tok\n", style=DIM); t.append((a.last_text or a.desc)[:28], style=DIM)
        else:
            t.append("[idle]", style=DIM)
        return t


class ReturnBox(Panel):
    DEFAULT_CSS = "ReturnBox { border: round #f0955a; height: 4; content-align: center middle; text-align: center; }"

    def render_state(self, s: SessionState) -> Text:
        back = s.agents and not s.active_agents and s.phase in ("thinking", "tool")
        t = Text(justify="center")
        t.append(f"back to main session · {s.effort or 'high'}\n", style=f"bold {OPUS}" if back else DIM)
        t.append("review + verify", style=FG if back else DIM)
        return t


class SessionLog(RichLog):
    DEFAULT_CSS = "SessionLog { border: round #3a3d4d; height: 10; border-title-color: #6b6f80; }"
    ACTOR_STYLE = {"opus": OPUS, "sonnet": SONNET, "fable": FABLE, "jev": JEV, "hook": DIM, "you": FG, "codex": WARN}

    def __init__(self):
        super().__init__(markup=False, wrap=False, max_lines=400)
        self.border_title = "session log"; self._seen = 0

    def refresh_state(self, s: SessionState) -> None:
        lines = list(s.log)
        if len(lines) < self._seen:
            self.clear(); self._seen = 0
        for line in lines[self._seen:]:
            t = Text(); t.append(f"{line.ts}  ", style=DIM)
            actor = line.actor.split()[0] if line.actor else "hook"
            t.append(f"{actor:<7}", style=f"bold {self.ACTOR_STYLE.get(actor, FG)}")
            t.append(line.text, style={"warn": WARN, "error": ERR}.get(line.level, FG))
            if line.right:
                t.append("   " + line.right, style=DIM)
            self.write(t)
        self._seen = len(lines)


class StatusBar(Panel):
    DEFAULT_CSS = "StatusBar { border: none; height: 1; padding: 0 1; background: #16171e; }"

    def render_state(self, s: SessionState) -> Text:
        t = Text()
        def kv(k: str, v: str, color: str) -> None:
            t.append(f"{k}: ", style=DIM); t.append("[", style=DIM); t.append(v, style=color); t.append("]  ", style=DIM)
        kv("effort", f"{s.effort or 'high'}/{s.subagent_effort}", OPUS)
        kv("subagents", f"{len(s.active_agents)}/{max(len([a for a in s.agents.values()]), 3)}", SONNET)
        kv("fable", "advising" if s.advisor.in_progress else ("on call" if s.advisor.model else "off"), FABLE)
        kv("jev", f"{s.jev_forks_total:,} forks" if s.jev_enabled else "off", JEV)
        kv("codex", "on" if s.codex_enabled else "off", WARN if s.codex_enabled else DIM)
        t.append(f"ctx {s.ctx_pct:.0f}%  ${s.cost:.2f}", style=DIM)
        if s.rate_5h:
            t.append(f"  5h {s.rate_5h:.0f}% 7d {s.rate_7d:.0f}%", style=WARN if s.rate_5h > 85 else DIM)
        t.append("   F1 help  F2 view  F3 zoom  F10 quit", style=DIM)
        return t


class TreeView(Vertical):
    """The whole agent tree (everything except the terminal pane)."""
    DEFAULT_CSS = """
    TreeView { height: 100%; }
    #tree-body { height: 1fr; }
    #center { width: 1fr; height: 100%; }
    #agents { height: 8; }
    """

    def compose(self) -> ComposeResult:
        yield Header(id="header")
        with Horizontal(id="tree-body"):
            yield AdvisorPanel(id="advisor")
            with Vertical(id="center"):
                yield MainSession(id="main")
                yield JevPanel(id="jev")
                yield Dispatcher(id="dispatcher")
                with Horizontal(id="agents"):
                    for k in AGENT_KINDS:
                        yield AgentBox(k)
                yield ReturnBox(id="return")
        yield SessionLog()
        yield StatusBar(id="status")

    def refresh_state(self, s: SessionState) -> None:
        for w in self.query(Panel):
            w.refresh_state(s)
        self.query_one(Dispatcher).refresh_state(s)
        self.query_one(SessionLog).refresh_state(s)
