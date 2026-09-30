#!/usr/bin/env bash
# Shared helpers for claude-harness hooks. Sourced, never executed.
# Contract: hooks are fail-open. Any internal error -> exit 0 with no stdout.
# shellcheck disable=SC2034

HARNESS_HOME="${HARNESS_HOME:-$HOME/.claude/harness}"
# Optional private env (API keys). chmod 600. Never printed.
[ -r "$HARNESS_HOME/env" ] && . "$HARNESS_HOME/env"

harness_read_input() {
  INPUT="$(cat 2>/dev/null || true)"
  [ -n "$INPUT" ] || INPUT='{}'
  eval "$(printf '%s' "$INPUT" | jq -r '@sh "H_EVENT=\(.hook_event_name // "") H_TOOL=\(.tool_name // "") H_CWD=\(.cwd // "") H_SESSION=\(.session_id // "") H_SOURCE=\(.source // "") H_TRIGGER=\(.trigger // "") H_STOP_ACTIVE=\((.stop_hook_active // false)|tostring) H_CMD=\(.tool_input.command // "") H_FILE=\(.tool_input.file_path // .tool_input.path // .tool_input.notebook_path // "") H_TRANSCRIPT=\(.transcript_path // "") H_AGENT_TYPE=\(.agent_type // "") H_AGENT_ID=\(.agent_id // "")"' 2>/dev/null)" || true
  : "${H_SESSION:=nosession}"
  [ -n "$H_CWD" ] || H_CWD="$PWD"
}

harness_host() { if [ -n "${CLAUDE_PROJECT_DIR:-}" ] || [ -n "${CLAUDECODE:-}" ]; then echo claude; else echo "${HARNESS_HOST:-codex}"; fi; }

harness_state_dir() { local d="$HARNESS_HOME/state/$H_SESSION"; mkdir -p "$d" 2>/dev/null; printf '%s' "$d"; }

# harness_emit <event> [extra-json-object]
harness_emit() {
  mkdir -p "$HARNESS_HOME/events" 2>/dev/null || return 0
  printf '%s' "$INPUT" | jq -c --arg ev "$1" --arg host "$(harness_host)" --argjson extra "${2:-{\}}" \
    '{ts: (now|todate), ev: $ev, sid: (.session_id // "nosession"), host: $host,
      tool: (.tool_name // null), agent_type: (.agent_type // null), agent_id: (.agent_id // null),
      cwd: (.cwd // null)} + $extra' >> "$HARNESS_HOME/events/$H_SESSION.jsonl" 2>/dev/null || true
}

harness_config() { jq -r --arg k "$1" '.[$k] // empty' "$HARNESS_HOME/config.json" 2>/dev/null; }
harness_jev_on() { [ "$(harness_config jev)" = "true" ] && { [ -n "${AI_GATEWAY_API_KEY:-}" ] || [ -n "${TYPESAFE_API_KEY:-}" ] || [ -n "${OPENROUTER_API_KEY:-}" ]; }; }
harness_bin() {
  local p
  for p in "$HOME/.local/bin/harness" "$(command -v harness 2>/dev/null)"; do
    [ -n "$p" ] && [ -x "$p" ] && { printf '%s' "$p"; return 0; }
  done
  return 1
}

harness_root() { git -C "$H_CWD" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$H_CWD"; }

harness_pm() {
  local r="$1"
  if [ -f "$r/bun.lock" ] || [ -f "$r/bun.lockb" ]; then echo bun
  elif [ -f "$r/pnpm-lock.yaml" ]; then echo pnpm
  elif [ -f "$r/yarn.lock" ]; then echo yarn
  else echo npm; fi
}

# Project-local binary first, then PATH. Never npx (no downloads inside hooks).
harness_tool_bin() {
  local r="$1" n="$2"
  if [ -x "$r/node_modules/.bin/$n" ]; then printf '%s' "$r/node_modules/.bin/$n"
  elif [ -x "$r/.venv/bin/$n" ]; then printf '%s' "$r/.venv/bin/$n"
  else command -v "$n" 2>/dev/null || true; fi
}

# Prints the project's fast check command, or nothing.
harness_check_cmd() {
  local r="$1" pm
  if [ -f "$r/.claude/harness.json" ]; then
    local c; c="$(jq -r '.check // empty' "$r/.claude/harness.json" 2>/dev/null)"
    [ -n "$c" ] && { printf '%s' "$c"; return 0; }
  fi
  if [ -f "$r/package.json" ]; then
    pm="$(harness_pm "$r")"
    local s
    for s in check typecheck type-check test:fast; do
      if jq -e --arg s "$s" '.scripts[$s] // empty' "$r/package.json" >/dev/null 2>&1; then printf '%s run %s' "$pm" "$s"; return 0; fi
    done
    if [ -f "$r/tsconfig.json" ] && [ -x "$r/node_modules/.bin/tsc" ]; then printf '%s' "node_modules/.bin/tsc --noEmit -p tsconfig.json"; return 0; fi
    if jq -e '.scripts.test // empty | select(test("no test specified") | not)' "$r/package.json" >/dev/null 2>&1; then printf 'CI=1 %s test' "$pm"; return 0; fi
  fi
  if [ -f "$r/pyproject.toml" ] || [ -f "$r/pytest.ini" ] || [ -f "$r/setup.cfg" ]; then
    if [ -f "$r/uv.lock" ]; then printf '%s' "uv run pytest -x -q"; return 0; fi
    if [ -x "$r/.venv/bin/pytest" ]; then printf '%s' ".venv/bin/pytest -x -q"; return 0; fi
    command -v pytest >/dev/null 2>&1 && { printf '%s' "pytest -x -q"; return 0; }
  fi
  [ -f "$r/go.mod" ] && { printf '%s' "go vet ./... && go test ./... -count=1"; return 0; }
  [ -f "$r/Cargo.toml" ] && { printf '%s' "cargo check --quiet"; return 0; }
  if [ -f "$r/Makefile" ]; then
    grep -qE '^check:' "$r/Makefile" && { printf '%s' "make check"; return 0; }
    grep -qE '^test:' "$r/Makefile" && { printf '%s' "make test"; return 0; }
  fi
  return 1
}

# Run a command with a wall-clock cap (macOS has no `timeout`).
harness_run_capped() { local secs="$1"; shift; perl -e 'alarm shift; exec @ARGV' "$secs" "$@"; }

harness_pre_decision() { jq -n --arg d "$1" --arg r "$2" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:$d,permissionDecisionReason:$r}}'; }
harness_ctx() { jq -n --arg e "$1" --arg c "$2" '{hookSpecificOutput:{hookEventName:$e,additionalContext:$c}}'; }
harness_log() { [ "${HARNESS_DEBUG:-0}" = "1" ] && printf '%s %s\n' "$(date +%H:%M:%S)" "$*" >> "$HARNESS_HOME/debug.log" 2>/dev/null; return 0; }
