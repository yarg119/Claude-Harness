#!/usr/bin/env bash
# UserPromptSubmit: log the prompt; ask Jev which worker should take it (sharp -> inject a route hint).
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
harness_read_input
harness_emit "Prompt" "$(printf '%s' "$INPUT" | jq -c '{prompt: ((.prompt // .user_input // "") | .[0:240])}')"
if harness_jev_on; then
  bin="$(harness_bin 2>/dev/null || true)"
  [ -n "$bin" ] && printf '%s' "$INPUT" | harness_run_capped 6 "$bin" jev-hook route 2>/dev/null || true
fi
exit 0
