"""Jev fork layer: cheap, non-generative decisions via TypeSafe AI's Jev (System One).

Forks (each maps a hook input to an optional hook output; everything is fail-open):
  route         UserPromptSubmit  -> which worker should take the prompt (Choice)
  tool_risk     PreToolUse Bash   -> is this command destructive / hard to reverse (Noul)
  retry_or_stop PostToolUseFailure-> is the agent digging in the wrong place (Noul)
Decisions are logged to ~/.claude/harness/jev/<session>.jsonl as {ts, fork, choice, p, confidence, verdict, ms, tokens}.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from typing import Any

from . import config, paths

OPENROUTER_URL = "https://openrouter.ai/api/v1/systemone"
OPENROUTER_MODEL = "typesafe/jev-1.13"
VERCEL_BASE_URL = "https://ai-gateway.vercel.sh/typesafe"   # TypeSafe-compatible API on Vercel AI Gateway
VERCEL_MODEL = "typesafe-ai/jev"
ROUTES = {
    "explorer": "The user wants to find, trace, or understand existing code: where something is, how it works, what calls what. Read-only.",
    "researcher": "The user needs external knowledge: a library API, version behaviour, documentation, migration notes, what is current.",
    "worker": "The user wants a specific, well-bounded code change made and tested; scope and acceptance are clear.",
    "plan": "The request is large, multi-file, ambiguous, or architectural; it needs a bounded contract and a plan before any edit.",
    "inline": "Small talk, a quick factual question, a one-line edit, a command to run, or a follow-up the main session can answer directly.",
}


# ---------- client ----------
class JevClient:
    def __init__(self, timeout: float = 4.0):
        self.timeout = timeout
        self.api_key = None; self.base_url = None; self.model = None
        if os.environ.get("AI_GATEWAY_API_KEY"):          # Vercel AI Gateway key (vck_...)
            self.backend = "vercel"; self.api_key = os.environ["AI_GATEWAY_API_KEY"]
            self.base_url = VERCEL_BASE_URL; self.model = VERCEL_MODEL
        elif os.environ.get("TYPESAFE_API_KEY"):           # direct TypeSafe key (honours TYPESAFE_BASE_URL)
            self.backend = "typesafe"; self.api_key = os.environ["TYPESAFE_API_KEY"]
            self.base_url = os.environ.get("TYPESAFE_BASE_URL") or None
            self.model = VERCEL_MODEL if (self.base_url and "vercel" in self.base_url) else None
        elif os.environ.get("OPENROUTER_API_KEY"):
            self.backend = "openrouter"
        else:
            self.backend = None

    def available(self) -> bool:
        return self.backend is not None

    def ask(self, state: dict[str, Any], questions: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], int]:
        """Return ({question: {choice|noul|score, probabilities, confidence}}, input_tokens)."""
        if self.backend in ("typesafe", "vercel"):
            return self._typesafe(state, questions)
        if self.backend == "openrouter":
            return self._openrouter(state, questions)
        raise RuntimeError("no Jev backend (set TYPESAFE_API_KEY or OPENROUTER_API_KEY)")

    def _typesafe(self, state, questions):
        from typesafe_sdk import Choice, Noul, Score, TypeSafeClient  # noqa: F401
        qs = {}
        for k, q in questions.items():
            if q["type"] == "choice":
                qs[k] = Choice(instructions=q["instructions"], criteria=q["criteria"])
            elif q["type"] == "noul":
                qs[k] = Noul(instructions=q["instructions"])
            else:
                qs[k] = Score(instructions=q["instructions"], criteria=q["criteria"])
        kwargs = {"timeout": self.timeout, "api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if self.model:
            kwargs["model"] = self.model
        with TypeSafeClient(**kwargs) as client:
            resp = client.system_one(state=state, questions=qs)
        out = {}
        for k, a in resp.answers.items():
            a = getattr(a, "root", a)
            d = a.model_dump() if hasattr(a, "model_dump") else dict(a)
            out[k] = d
        usage = getattr(resp, "usage", None)
        return out, int(getattr(usage, "input_tokens", 0) or 0)

    def _openrouter(self, state, questions):
        body = json.dumps({"model": OPENROUTER_MODEL, "state": state, "questions": questions}).encode()
        req = urllib.request.Request(OPENROUTER_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode())
        answers = data.get("answers") or data.get("decisions") or {}
        usage = data.get("usage") or {}
        return {k: dict(v) for k, v in answers.items()}, int(usage.get("input_tokens", 0) or 0)


# ---------- helpers ----------
def _log(session: str, row: dict[str, Any]) -> None:
    try:
        paths.ensure_dirs()
        with paths.jev_file(session or "nosession").open("a") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **row}) + "\n")
    except OSError:
        pass


def _repo_signals(cwd: str) -> dict[str, Any]:
    sig: dict[str, Any] = {}
    try:
        dirty = subprocess.run(["git", "-C", cwd, "status", "--porcelain"], capture_output=True, text=True, timeout=2).stdout
        sig["dirty_files"] = len(dirty.splitlines())
        branch = subprocess.run(["git", "-C", cwd, "symbolic-ref", "--short", "-q", "HEAD"], capture_output=True, text=True, timeout=2).stdout.strip()
        sig["branch"] = branch
    except (OSError, subprocess.SubprocessError):
        pass
    for marker, key in (("package.json", "node"), ("pyproject.toml", "python"), ("go.mod", "go"), ("Cargo.toml", "rust")):
        if os.path.exists(os.path.join(cwd, marker)):
            sig.setdefault("stack", []).append(key)
    return sig


def _recent_events(session: str, n: int = 4) -> list[str]:
    try:
        lines = paths.events_file(session).read_text().splitlines()[-n:]
        out = []
        for line in lines:
            ev = json.loads(line)
            out.append(" ".join(str(ev.get(k)) for k in ("ev", "tool", "cmd", "file") if ev.get(k)))
        return out
    except (OSError, ValueError):
        return []


def _noul_p(ans: dict[str, Any]) -> float:
    v = ans.get("noul")
    if isinstance(v, dict):  # some shapes return {"true": p, "false": q}
        return float(v.get("true", 0.0))
    return float(v or 0.0)


# ---------- forks ----------
def fork_route(client: JevClient, hook: dict[str, Any], threshold: float) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    prompt = (hook.get("prompt") or hook.get("user_input") or "")[:2000]
    cwd = hook.get("cwd") or os.getcwd()
    if not prompt.strip() or prompt.startswith("/"):
        return None, {"skipped": "empty or slash command"}
    state = {"user_prompt": prompt, "repo": _repo_signals(cwd), "recent_events": _recent_events(hook.get("session_id", ""))}
    q = {"route": {"type": "choice", "instructions": "Which harness worker should take this prompt first? Pick the single best fit.", "criteria": ROUTES}}
    answers, tokens = client.ask(state, q)
    a = answers["route"]
    choice, conf = a.get("choice"), float(a.get("confidence") or 0)
    probs = a.get("probabilities") or {}
    p = float(probs.get(choice, conf) or conf)
    sharp = p >= threshold and choice in ("explorer", "researcher", "worker", "plan")
    meta = {"choice": choice, "p": round(p, 3), "confidence": round(conf, 3), "verdict": "sharp" if sharp else "split", "tokens": tokens}
    if not sharp:
        return None, meta
    hint = {
        "explorer": "delegate the exploration to the `explorer` subagent and keep this context for the decision",
        "researcher": "delegate the lookup to the `researcher` subagent",
        "worker": "write a one-line acceptance criterion, then hand the change to the `worker` subagent",
        "plan": "run /plan-contract before editing anything",
    }[choice]
    ctx = f"[harness/jev] route: {choice} (p={p:.2f}). Unless the prompt says otherwise, {hint}."
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}, meta


def fork_tool_risk(client: JevClient, hook: dict[str, Any], threshold: float) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    cmd = (hook.get("tool_input") or {}).get("command", "")
    if not cmd:
        return None, {"skipped": "no command"}
    cwd = hook.get("cwd") or os.getcwd()
    state = {"shell_command": cmd[:1500], "cwd": cwd, "repo": _repo_signals(cwd)}
    q = {"risky": {"type": "noul", "instructions": "Would running this shell command destroy or overwrite data, change shared or remote state (push, publish, deploy, drop, delete), or be hard to reverse? Reading, listing, building and running tests are not risky."}}
    answers, tokens = client.ask(state, q)
    p = _noul_p(answers["risky"])
    ask_at = max(threshold, 0.85)
    verdict = "sharp" if (p >= ask_at or p <= 1 - ask_at) else "split"
    meta = {"choice": "risky" if p >= ask_at else ("safe" if p <= 1 - ask_at else "unsure"), "p": round(p, 3), "verdict": verdict, "tokens": tokens}
    if p >= ask_at:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                       "permissionDecisionReason": f"harness/jev: this command looks destructive or hard to reverse (p={p:.2f}). Confirm."}}, meta
    return None, meta


def fork_retry_or_stop(client: JevClient, hook: dict[str, Any], threshold: float) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    err = str(hook.get("error") or hook.get("tool_response") or "")[:1200]
    repeat = int(hook.get("harness_repeat") or 0)
    state = {"tool": hook.get("tool_name"), "tool_input": json.dumps(hook.get("tool_input") or {})[:800], "error": err,
             "identical_failures_so_far": repeat, "recent_events": _recent_events(hook.get("session_id", ""), 8)}
    q = {"wrong_place": {"type": "noul", "instructions": "The agent has hit the same error repeatedly. Is it digging in the wrong place, so that another retry of the same approach is unlikely to work and it should stop, consult its advisor, and re-plan?"}}
    answers, tokens = client.ask(state, q)
    p = _noul_p(answers["wrong_place"])
    meta = {"choice": "stop" if p >= threshold else "retry", "p": round(p, 3), "verdict": "sharp" if abs(p - 0.5) >= threshold - 0.5 else "split", "tokens": tokens}
    if p >= threshold:
        return {"hookSpecificOutput": {"hookEventName": "PostToolUseFailure",
                                       "additionalContext": f"[harness/jev] the same error has failed {repeat}x and looks like the wrong place (p={p:.2f}). Stop retrying; consult the advisor and re-plan from the evidence."}}, meta
    return None, meta


FORKS = {"route": fork_route, "tool_risk": fork_tool_risk, "retry_or_stop": fork_retry_or_stop}


def hook(fork: str, hook_input: dict[str, Any]) -> dict[str, Any] | None:
    cfg = config.load()
    if not cfg.get("jev"):
        return None
    client = JevClient()
    if not client.available():
        return None
    session = hook_input.get("session_id", "")
    t0 = time.time()
    try:
        out, meta = FORKS[fork](client, hook_input, float(cfg.get("jev_threshold", 0.8)))
        _log(session, {"fork": fork, "ms": int((time.time() - t0) * 1000), **meta})
        return out
    except Exception as e:  # noqa: BLE001  fail-open
        _log(session, {"fork": fork, "ms": int((time.time() - t0) * 1000), "error": str(e)[:200]})
        return None


def ping() -> dict[str, Any]:
    client = JevClient()
    if not client.available():
        return {"ok": False, "detail": "no key (AI_GATEWAY_API_KEY, TYPESAFE_API_KEY or OPENROUTER_API_KEY)"}
    t0 = time.time()
    try:
        answers, tokens = client.ask({"shell_command": "ls -la"}, {"risky": {"type": "noul", "instructions": "Is this command destructive?"}})
        return {"ok": True, "detail": f"{client.backend} {int((time.time()-t0)*1000)} ms, p(risky)={_noul_p(answers['risky']):.2f}, {tokens} tokens"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"{client.backend}: {e}"}


def test_forks() -> list[dict[str, Any]]:
    """One sample decision per fork (does not require the toggle to be on)."""
    client = JevClient()
    if not client.available():
        return [{"error": "no AI_GATEWAY_API_KEY / TYPESAFE_API_KEY / OPENROUTER_API_KEY"}]
    thr = float(config.load().get("jev_threshold", 0.8))
    samples = {
        "route": {"prompt": "Where is the retry logic for the payment webhook and what calls it?", "cwd": os.getcwd(), "session_id": "jev-test"},
        "tool_risk": {"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}, "cwd": os.getcwd()},
        "retry_or_stop": {"tool_name": "Bash", "error": "TypeError: Cannot read properties of undefined (reading 'id')", "harness_repeat": 3, "session_id": "jev-test"},
    }
    rows = []
    for fork, inp in samples.items():
        t0 = time.time()
        try:
            out, meta = FORKS[fork](client, inp, thr)
            rows.append({"fork": fork, "ms": int((time.time() - t0) * 1000), **meta, "would_inject": bool(out)})
        except Exception as e:  # noqa: BLE001
            rows.append({"fork": fork, "error": str(e)[:200]})
    return rows
