"""Pure session state + reducers fed by hook events, transcript lines, status-line JSON and Jev rows."""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

AGENT_KINDS = ("worker", "explorer", "researcher")
_KIND_ALIASES = {
    "explore": "explorer", "code-explorer": "explorer", "feature-dev:code-explorer": "explorer",
    "plan": "explorer", "code-architect": "explorer",
    "general-purpose": "worker", "claude": "worker", "codex:codex-rescue": "worker", "codex-rescue": "worker",
    "code-reviewer": "reviewer", "feature-dev:code-reviewer": "reviewer", "claude-code-guide": "researcher",
}


def agent_kind(type_name: str) -> str:
    t = (type_name or "").lower()
    if t in AGENT_KINDS or t == "reviewer":
        return t
    return _KIND_ALIASES.get(t, "other")


def model_short(model: str | None) -> str:
    m = (model or "").lower()
    for k, v in (("fable", "fable"), ("opus", "opus"), ("sonnet", "sonnet"), ("haiku", "haiku")):
        if k in m:
            ver = re.search(r"(\d)-(\d)", m)
            return f"{v} {ver.group(1)}.{ver.group(2)}" if ver else v
    return m or "?"


@dataclass
class LogLine:
    ts: str
    actor: str       # opus | sonnet | fable | jev | hook | codex
    text: str
    right: str = ""
    level: str = ""  # "" | warn | error


@dataclass
class AgentInfo:
    id: str
    type_name: str
    kind: str
    status: str = "running"   # running | done
    desc: str = ""
    started: float = field(default_factory=time.time)
    ended: float | None = None
    current_tool: str = ""
    last_text: str = ""
    out_tokens: int = 0
    series: deque = field(default_factory=lambda: deque(maxlen=40))


@dataclass
class AdvisorState:
    model: str = ""
    calls: int = 0
    tokens_read: int = 0
    tokens_out: int = 0
    last_kind: str = ""      # before a plan | error repeats | before done
    last_status: str = ""    # Reviewed | Declined | Unavailable
    last_applied: str = ""
    last_ts: str = ""
    in_progress: bool = False


@dataclass
class ForkStats:
    sharp: int = 0
    split: int = 0
    last_p: float = 0.0
    last_choice: str = ""
    last_verdict: str = ""

    @property
    def total(self) -> int:
        return self.sharp + self.split

    @property
    def sharp_ratio(self) -> float:
        return self.sharp / self.total if self.total else 0.0


@dataclass
class SessionState:
    session_id: str = ""
    cwd: str = ""
    started: float = field(default_factory=time.time)
    # main session
    model: str = "opus"
    effort: str = ""
    ctx_pct: float = 0.0
    ctx_size: int = 0
    cost: float = 0.0
    phase: str = "idle"          # idle | thinking | tool | awaiting | done
    current_tool: str = ""
    last_text: str = ""
    turn_edits: int = 0
    turn_failures: int = 0
    turn_advisor_calls: int = 0
    total_edits: int = 0
    stop_blocks: int = 0
    guard_denies: int = 0
    rate_5h: float = 0.0
    rate_7d: float = 0.0
    fast_mode: bool = False
    # layers
    advisor: AdvisorState = field(default_factory=AdvisorState)
    agents: dict[str, AgentInfo] = field(default_factory=dict)
    jev: dict[str, ForkStats] = field(default_factory=lambda: {"route": ForkStats(), "tool_risk": ForkStats(), "retry_or_stop": ForkStats()})
    jev_enabled: bool = False
    codex_enabled: bool = False
    subagent_effort: str = "medium"
    tokens_per_s: deque = field(default_factory=lambda: deque([0.0] * 30, maxlen=30))
    log: deque = field(default_factory=lambda: deque(maxlen=300))
    _pending_tools: dict[str, tuple[str, str]] = field(default_factory=dict)   # tool_use_id -> (name, desc)
    _pending_dispatch: deque = field(default_factory=deque)                     # (subagent_type, description) awaiting a transcript
    _dispatch_ids: dict[str, str] = field(default_factory=dict)                 # Agent tool_use_id -> subagent_type
    _last_out_tokens: int = 0
    _last_out_ts: float = 0.0

    # ---- helpers ----
    def add_log(self, actor: str, text: str, right: str = "", level: str = "", ts: str | None = None) -> None:
        self.log.append(LogLine(ts or time.strftime("%H:%M:%S"), actor, text[:160], right[:60], level))

    @property
    def active_agents(self) -> list[AgentInfo]:
        return [a for a in self.agents.values() if a.status == "running"]

    def register_agent(self, agent_id: str, type_name: str | None = None, desc: str = "") -> AgentInfo:
        a = self.agents.get(agent_id)
        if a is None:
            if type_name is None and self._pending_dispatch:
                type_name, desc = self._pending_dispatch.popleft()
            a = AgentInfo(agent_id, type_name or "agent", agent_kind(type_name or ""), desc=desc)
            self.agents[agent_id] = a
            self.add_log("sonnet", f"{a.kind} started ({a.type_name})" + (f": {desc}" if desc else ""), "effort medium")
        elif type_name and a.type_name in ("agent", "?"):
            a.type_name, a.kind = type_name, agent_kind(type_name)
        return a

    def agent_for_kind(self, kind: str) -> AgentInfo | None:
        running = [a for a in self.agents.values() if a.kind == kind and a.status == "running"]
        if running:
            return running[-1]
        done = [a for a in self.agents.values() if a.kind == kind]
        return done[-1] if done else None

    @property
    def jev_forks_total(self) -> int:
        return sum(f.total for f in self.jev.values())

    # ---- reducers ----
    def apply_status(self, s: dict[str, Any]) -> None:
        self.model = (s.get("model") or {}).get("display_name") or self.model
        self.effort = (s.get("effort") or {}).get("level") or self.effort
        cw = s.get("context_window") or {}
        self.ctx_pct = float(cw.get("used_percentage") or self.ctx_pct or 0)
        self.ctx_size = int(cw.get("context_window_size") or self.ctx_size or 0)
        self.cost = float((s.get("cost") or {}).get("total_cost_usd") or self.cost or 0)
        rl = s.get("rate_limits") or {}
        self.rate_5h = float((rl.get("five_hour") or {}).get("used_percentage") or 0)
        self.rate_7d = float((rl.get("seven_day") or {}).get("used_percentage") or 0)
        self.fast_mode = bool(s.get("fast_mode"))

    def apply_config(self, cfg: dict[str, Any]) -> None:
        self.jev_enabled = bool(cfg.get("jev"))
        self.codex_enabled = bool(cfg.get("codex"))

    def apply_event(self, ev: dict[str, Any]) -> None:
        kind = ev.get("ev", "")
        ts = (ev.get("ts") or "")[11:19] or None
        if kind == "SessionStart":
            self.cwd = ev.get("cwd") or self.cwd
            self.add_log("hook", f"session {ev.get('source') or 'start'} · check: {ev.get('check') or 'none'}", ts=ts)
        elif kind == "Prompt":
            self.phase = "thinking"; self.turn_edits = 0; self.turn_failures = 0; self.turn_advisor_calls = 0
            self.add_log("you", ev.get("prompt", ""), ts=ts)
        elif kind == "SubagentStart":
            self.register_agent(ev.get("agent_id") or f"a{len(self.agents)}", ev.get("agent_type") or "?")
        elif kind == "SubagentStop":
            a = self.agents.get(ev.get("agent_id") or "")
            if a:
                a.status = "done"; a.ended = time.time(); a.last_text = ev.get("last") or a.last_text
                self.add_log("sonnet", f"{a.kind} done → back to main session", ev.get("stop_reason") or "", ts=ts)
        elif kind == "Guard":
            v = ev.get("verdict"); self.guard_denies += v == "deny"
            self.add_log("hook", f"guard {v}: {ev.get('reason', '')}", "", "warn" if v == "deny" else "", ts=ts)
        elif kind == "Edit":
            self.turn_edits += 1; self.total_edits += 1
        elif kind == "Lint":
            self.add_log("hook", f"post-edit {'diagnostics' if ev.get('rc') else 'formatted'}: {ev.get('file', '')}", "", "warn" if ev.get("rc") else "", ts=ts)
        elif kind == "PostToolUseFailure":
            self.turn_failures += 1
            self.add_log("hook", f"tool failed x{ev.get('repeat', 1)}: {ev.get('error', '')}", "", "warn", ts=ts)
        elif kind == "StopGate":
            if ev.get("result") == "block":
                self.stop_blocks = int(ev.get("blocks") or self.stop_blocks + 1)
                self.add_log("hook", f"stop gate blocked ({ev.get('blocks')}/2): {ev.get('check')}", "", "error", ts=ts)
            else:
                self.add_log("hook", f"stop gate pass: {ev.get('check')}", "commit ready", ts=ts)
        elif kind == "Stop":
            self.phase = "awaiting"
        elif kind == "Notification":
            self.phase = "awaiting"
            self.add_log("hook", f"notification: {ev.get('notification') or ev.get('message') or ''}", ts=ts)
        elif kind == "PreCompact":
            self.add_log("hook", "compacting context (snapshot saved)", ts=ts)
        elif kind == "PostModelSwitch":
            self.add_log("hook", f"model {model_short(ev.get('from_model'))} → {model_short(ev.get('to_model'))}", ts=ts)
        elif kind == "SessionEnd":
            self.phase = "done"; self.add_log("hook", "session ended", ts=ts)

    def apply_jev(self, row: dict[str, Any]) -> None:
        fork = row.get("fork", "")
        f = self.jev.setdefault(fork, ForkStats())
        ts = (row.get("ts") or "")[11:19] or None
        if row.get("error"):
            self.add_log("jev", f"{fork} error: {row['error'][:60]}", "", "warn", ts=ts)
            return
        if row.get("skipped"):
            return
        v = row.get("verdict", "split")
        if v == "sharp":
            f.sharp += 1
        else:
            f.split += 1
        f.last_p = float(row.get("p") or 0); f.last_choice = str(row.get("choice") or ""); f.last_verdict = v
        arrow = "→ code" if v == "sharp" else "→ opus"
        self.add_log("jev", f"{fork.replace('_', ' ')} → {f.last_choice}", f"p={f.last_p:.2f} {v} {arrow}", ts=ts)

    def apply_transcript(self, line: dict[str, Any], agent_id: str | None = None) -> None:
        t = line.get("type")
        msg = line.get("message") or {}
        ts = (line.get("timestamp") or "")[11:19] or None
        if t == "assistant":
            if not agent_id:
                self.effort = line.get("perTurnEffort") or line.get("effort") or self.effort
                if line.get("advisorModel"):
                    self.advisor.model = str(line["advisorModel"])
                self.model = model_short(msg.get("model")) or self.model
            content = msg.get("content")
            if not isinstance(content, list):
                return
            a = self.register_agent(agent_id) if agent_id else None
            usage = msg.get("usage") or {}
            out_tok = int(usage.get("output_tokens") or 0)
            if a is not None:
                a.out_tokens += out_tok
                a.series.append(out_tok)
            self._rate(out_tok)
            for c in content:
                ct = c.get("type")
                if ct == "thinking" and not agent_id:
                    self.phase = "thinking"
                elif ct == "text" and c.get("text"):
                    txt = c["text"].strip()
                    if a is not None:
                        a.last_text = txt[:200]
                    else:
                        self.last_text = txt[:200]
                        if self.advisor.in_progress:
                            self.advisor.last_applied = txt.split("\n")[0][:120]; self.advisor.in_progress = False
                        self.add_log("opus" if "opus" in self.model else self.model.split()[0], txt.split("\n")[0][:110], f"effort {self.effort}" if self.effort else "", ts=ts)
                elif ct == "tool_use":
                    name = c.get("name", ""); inp = c.get("input") or {}
                    self._pending_tools[c.get("id", "")] = (name, str(inp.get("description") or inp.get("subagent_type") or "")[:60])
                    if a is not None:
                        a.current_tool = name
                    else:
                        self.phase = "tool"; self.current_tool = name
                        if name == "Agent":
                            st = str(inp.get("subagent_type") or "general-purpose"); d = str(inp.get("description", ""))[:60]
                            self._pending_dispatch.append((st, d)); self._dispatch_ids[c.get("id", "")] = st
                            self.add_log("opus", f"dispatch {st}: {d}", "effort medium", ts=ts)
                        elif name in ("Edit", "Write", "MultiEdit"):
                            self.add_log("opus", f"{name.lower()} {str(inp.get('file_path', '')).split('/')[-1]}", "", ts=ts)
                        elif name == "Bash":
                            self.add_log("opus", f"$ {str(inp.get('command', ''))[:90]}", "", ts=ts)
                elif ct == "server_tool_use" and c.get("name") == "advisor":
                    self.advisor.calls += 1; self.turn_advisor_calls += 1; self.advisor.in_progress = True
                    self.advisor.last_kind = self._advisor_kind(); self.advisor.last_ts = ts or ""
                    self.add_log("fable", f"advising · {self.advisor.last_kind}", "reads full session", ts=ts)
                elif ct == "advisor_tool_result":
                    rc = (c.get("content") or {}).get("type", "")
                    self.advisor.last_status = {"advisor_result": "Reviewed", "advisor_redacted_result": "Reviewed", "advisor_tool_result_error": "Unavailable"}.get(rc, "Declined")
                    if rc == "advisor_result" and (c.get("content") or {}).get("text"):
                        self.advisor.last_applied = c["content"]["text"].split("\n")[0][:120]
                    self.add_log("fable", f"{self.advisor.last_status.lower()}", (c.get("content") or {}).get("error_code", ""), ts=ts)
            for it in usage.get("iterations") or []:
                if it.get("type") == "advisor_message":
                    self.advisor.tokens_read += int(it.get("input_tokens") or 0) + int(it.get("cache_read_input_tokens") or 0) + int(it.get("cache_creation_input_tokens") or 0)
                    self.advisor.tokens_out += int(it.get("output_tokens") or 0)
        elif t == "user":
            content = msg.get("content")
            if isinstance(content, list):
                for c in content:
                    if c.get("type") == "tool_result":
                        name, desc = self._pending_tools.pop(c.get("tool_use_id", ""), ("", ""))
                        if c.get("is_error") and not agent_id:
                            self.add_log("hook", f"{name or 'tool'} error", "", "warn", ts=ts)
                        if not agent_id and name == "Agent":
                            self.phase = "thinking"
                            st = self._dispatch_ids.pop(c.get("tool_use_id", ""), "")
                            for ag in self.agents.values():   # close the oldest running agent of that kind
                                if ag.status == "running" and (not st or ag.type_name == st or agent_kind(st) == ag.kind):
                                    ag.status = "done"; ag.ended = time.time()
                                    self.add_log("sonnet", f"{ag.kind} returned → back to main session", "review + verify", ts=ts)
                                    break
            elif isinstance(content, str) and not agent_id and not content.startswith("<"):
                self.phase = "thinking"

    def _advisor_kind(self) -> str:
        if self.turn_failures >= 2:
            return "error repeats"
        if self.turn_edits == 0:
            return "before a plan"
        return "before done"

    def _rate(self, out_tok: int) -> None:
        now = time.time()
        if self._last_out_ts and now - self._last_out_ts > 0:
            self.tokens_per_s.append(min(out_tok / max(now - self._last_out_ts, 0.5), 400.0))
        self._last_out_ts = now
