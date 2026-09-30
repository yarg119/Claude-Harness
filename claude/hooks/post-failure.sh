#!/usr/bin/env bash
# PostToolUseFailure: count repeated identical failures; at 3, route retry-or-stop (Jev or deterministic).
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
harness_read_input
STATE="$(harness_state_dir)"
err="$(printf '%s' "$INPUT" | jq -r '(.error // .tool_response.error // .tool_response // "") | tostring | .[0:200]' 2>/dev/null)"
key="$(printf '%s|%s' "$H_TOOL" "$err" | cksum | cut -d' ' -f1)"
n=$(( $(cat "$STATE/fail_$key" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$STATE/fail_$key"
harness_emit "PostToolUseFailure" "$(jq -n --arg e "$err" --argjson n "$n" '{error:$e, repeat:$n}')"
[ "$n" -ge 3 ] || exit 0
if harness_jev_on; then
  bin="$(harness_bin 2>/dev/null || true)"
  if [ -n "$bin" ]; then out="$(printf '%s' "$INPUT" | jq -c --argjson n "$n" '. + {harness_repeat:$n}' | harness_run_capped 6 "$bin" jev-hook retry_or_stop 2>/dev/null || true)"; [ -n "$out" ] && { printf '%s\n' "$out"; exit 0; }; fi
fi
[ "$n" -eq 3 ] && harness_ctx PostToolUseFailure "harness: the same $H_TOOL error has now happened $n times. Stop retrying the same fix. Consult the advisor, then re-plan from the evidence."
exit 0
