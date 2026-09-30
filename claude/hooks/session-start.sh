#!/usr/bin/env bash
# SessionStart: register the session for the dashboard, reset counters, inject context.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
harness_read_input
STATE="$(harness_state_dir)"
ROOT="$(harness_root)"
mkdir -p "$HARNESS_HOME/sessions"
jq -n --arg sid "$H_SESSION" --arg t "$H_TRANSCRIPT" --arg cwd "$H_CWD" --arg root "$ROOT" --arg src "$H_SOURCE" --arg host "$(harness_host)" \
  '{session_id:$sid, transcript_path:$t, cwd:$cwd, root:$root, source:$src, host:$host, started_at:(now|todate)}' \
  > "$HARNESS_HOME/sessions/$H_SESSION.json" 2>/dev/null || true
case "$H_SOURCE" in
  startup|clear|"") echo 0 > "$STATE/stop_blocks"; : > "$STATE/edited"; : > "$STATE/edited.all"; rm -f "$STATE"/fail_* 2>/dev/null
                    git -C "$ROOT" rev-parse HEAD > "$STATE/start_commit" 2>/dev/null || true ;;
esac
# prune state older than 7 days
find "$HARNESS_HOME/state" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} + 2>/dev/null || true
CHECK="$(harness_check_cmd "$ROOT" 2>/dev/null || true)"
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  { printf 'export HARNESS_STATE_DIR=%q\n' "$STATE"; [ -n "$CHECK" ] && printf 'export HARNESS_CHECK_CMD=%q\n' "$CHECK"; } >> "$CLAUDE_ENV_FILE" 2>/dev/null || true
fi
harness_emit "SessionStart" "$(jq -n --arg src "$H_SOURCE" --arg check "$CHECK" '{source:$src, check:$check}')"

ctx=""
add() { ctx="${ctx}$1"$'\n'; }
if [ "$H_SOURCE" != "compact" ]; then
  if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    br="$(git -C "$ROOT" symbolic-ref --short -q HEAD 2>/dev/null || git -C "$ROOT" rev-parse --short HEAD 2>/dev/null)"
    dirty="$(git -C "$ROOT" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    add "[harness] project=$(basename "$ROOT") branch=$br dirty=$dirty files"
    add "[harness] last commits:"
    add "$(git -C "$ROOT" log --oneline -10 2>/dev/null)"
  else
    add "[harness] project=$(basename "$ROOT") (not a git repo)"
  fi
  if [ -n "$CHECK" ]; then add "[harness] check command: $CHECK"; else add "[harness] check command: none discovered. Set .claude/harness.json {\"check\": \"...\"} so the stop gate can run tests."; fi
fi
if [ -f "$ROOT/.claude/state/contract.md" ]; then add "[harness] contract: .claude/state/contract.md ($(wc -l < "$ROOT/.claude/state/contract.md" | tr -d ' ') lines)"; else add "[harness] contract: none (run /plan-contract before multi-file work)"; fi
if [ -f "$ROOT/.claude/state/progress.json" ]; then add "[harness] progress (.claude/state/progress.json):"; add "$(jq -c '{goal, next, blockers, updated_at}' "$ROOT/.claude/state/progress.json" 2>/dev/null | head -c 1500)"; fi
if [ "$H_SOURCE" = "compact" ] && [ -f "$STATE/precompact.txt" ]; then add "[harness] before compaction:"; add "$(head -c 2500 "$STATE/precompact.txt")"; fi
codex_state="off"; [ "$(harness_config codex)" = "true" ] && codex_state="on"
jev_state="off"; harness_jev_on && jev_state="on"
add "[harness] toggles: codex=$codex_state jev=$jev_state. Rule: consult the advisor before a multi-file plan, when the same error repeats, and before declaring done. Guard, post-edit and stop-gate hooks are active; if one blocks you, fix the cause or ask the user. Never work around a hook."
ctx="$(printf '%s' "$ctx" | head -c 6000)"
if [ "$(harness_host)" = "claude" ]; then harness_ctx SessionStart "$ctx"; else printf '%s\n' "$ctx"; fi
exit 0
