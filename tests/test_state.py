import json
from pathlib import Path

from claude_harness.state import SessionState, agent_kind, model_short


def asst(content, **top):
    return {"type": "assistant", "timestamp": "2026-09-30T11:00:00Z", "message": {"model": "claude-opus-5-5", "content": content,
            "usage": {"output_tokens": 50, "iterations": top.pop("iterations", [])}}, "effort": "high", "advisorModel": "claude-fable-5-1", **top}


def test_model_and_kind_helpers():
    assert model_short("claude-opus-5-5") == "opus 5.5" and model_short("claude-fable-5-1") == "fable 5.1"
    assert agent_kind("Explore") == "explorer" and agent_kind("worker") == "worker" and agent_kind("feature-dev:code-reviewer") == "reviewer"


def test_advisor_call_counts_and_kind():
    s = SessionState()
    s.apply_event({"ev": "Prompt", "prompt": "add a feature"})
    s.apply_transcript(asst([{"type": "text", "text": "Let me consult the advisor."},
                             {"type": "server_tool_use", "id": "srv1", "name": "advisor", "input": {}},
                             {"type": "advisor_tool_result", "tool_use_id": "srv1", "content": {"type": "advisor_redacted_result", "encrypted_content": "x"}}],
                            iterations=[{"type": "message", "input_tokens": 1}, {"type": "advisor_message", "input_tokens": 120000, "output_tokens": 900}]))
    assert s.advisor.calls == 1 and s.advisor.tokens_read == 120000 and s.advisor.last_kind == "before a plan"
    assert s.advisor.last_status == "Reviewed" and s.advisor.model == "claude-fable-5-1" and s.effort == "high"
    s.apply_transcript(asst([{"type": "text", "text": "Applying the advice: run the migration first."}]))
    assert s.advisor.last_applied.startswith("Applying the advice")


def test_agents_lifecycle_via_events_and_transcript():
    s = SessionState()
    s.apply_event({"ev": "SubagentStart", "agent_id": "a1", "agent_type": "explorer"})
    s.apply_transcript(asst([{"type": "tool_use", "id": "t1", "name": "Grep", "input": {"pattern": "x"}}]), agent_id="a1")
    assert s.agent_for_kind("explorer").current_tool == "Grep" and s.active_agents
    s.apply_event({"ev": "SubagentStop", "agent_id": "a1", "last": "found it", "stop_reason": "end_turn"})
    assert s.agent_for_kind("explorer").status == "done" and not s.active_agents


def test_jev_and_gates():
    s = SessionState()
    s.apply_jev({"fork": "route", "choice": "explorer", "p": 0.86, "verdict": "sharp"})
    s.apply_jev({"fork": "route", "choice": "worker", "p": 0.48, "verdict": "split"})
    assert s.jev["route"].sharp == 1 and s.jev["route"].split == 1 and s.jev_forks_total == 2
    s.apply_event({"ev": "StopGate", "result": "block", "blocks": 1, "check": "npm test"})
    s.apply_event({"ev": "Guard", "verdict": "deny", "reason": "rm -rf /"})
    assert s.stop_blocks == 1 and s.guard_denies == 1 and s.log[-1].level == "warn"


def test_reducer_survives_real_transcript():
    """Parse this machine's transcripts (read-only) if present; must not raise."""
    root = Path.home() / ".claude" / "projects"
    files = sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:3] if root.exists() else []
    for f in files:
        s = SessionState()
        for line in f.read_text(errors="replace").splitlines()[:400]:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            s.apply_transcript(d)
        assert s.model
