from claude_harness.merge import deep_merge, drop_hook_groups


def test_objects_merge_and_arrays_union():
    base = {"permissions": {"allow": ["Bash(vercel *)"]}, "tui": "fullscreen"}
    add = {"permissions": {"allow": ["Bash(git status)", "Bash(vercel *)"], "deny": ["Read(./.env)"]}, "model": "opus"}
    out = deep_merge(base, add)
    assert out["permissions"]["allow"] == ["Bash(vercel *)", "Bash(git status)"]
    assert out["permissions"]["deny"] == ["Read(./.env)"]
    assert out["tui"] == "fullscreen" and out["model"] == "opus"


def test_idempotent():
    base = {"a": [1, {"x": 1}], "b": {"c": 1}}
    once = deep_merge(base, base)
    assert deep_merge(once, base) == once == base


def test_drop_hook_groups_removes_only_matching():
    s = {"hooks": {"PreToolUse": [
        {"matcher": "Grep|Glob|Task", "hooks": [{"type": "command", "command": "/x/puppetmaster invocation-gate"}]},
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "/home/u/.claude/hooks/pre-tool-guard.sh"}]},
    ], "Stop": [{"hooks": [{"type": "command", "command": "/x/puppetmaster stop"}]}]}, "tui": "fullscreen"}
    out = drop_hook_groups(s, "puppetmaster")
    assert list(out["hooks"]) == ["PreToolUse"]
    assert out["hooks"]["PreToolUse"][0]["matcher"] == "Bash"
    assert out["tui"] == "fullscreen"
    assert "hooks" not in drop_hook_groups(out, ".claude/hooks")
