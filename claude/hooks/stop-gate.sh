#!/usr/bin/env bash
# Stop: if files were edited this turn, run the project's check command; block (max 2/session) on failure.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
harness_read_input
STATE="$(harness_state_dir)"; ROOT="$(harness_root)"
harness_emit "Stop" "$(printf '%s' "$INPUT" | jq -c '{last: ((.last_assistant_message // "") | .[0:240]), active: (.stop_hook_active // false)}')"
[ "${HARNESS_STOP_GATE:-on}" = "off" ] && exit 0
[ "$(jq -r '.stopGate // true' "$ROOT/.claude/harness.json" 2>/dev/null)" = "false" ] && exit 0
[ -s "$STATE/edited" ] || exit 0
last="$(printf '%s' "$INPUT" | jq -r '(.last_assistant_message // "") | .[-200:]' 2>/dev/null)"
[[ "$last" =~ \?[[:space:]]*$ ]] && exit 0          # asking the user; keep the marker armed
mv "$STATE/edited" "$STATE/edited.last" 2>/dev/null; : > "$STATE/edited"   # consume before running
blocks="$(cat "$STATE/stop_blocks" 2>/dev/null || echo 0)"
[ "$blocks" -ge 2 ] && { harness_log "stop gate: max blocks reached"; exit 0; }
cmd="$(harness_check_cmd "$ROOT" 2>/dev/null || true)"
[ -n "$cmd" ] || exit 0
( cd "$ROOT" && CI=1 FORCE_COLOR=0 harness_run_capped 150 bash -lc "$cmd" ) > "$STATE/last_check.txt" 2>&1; rc=$?
if [ "$rc" -eq 0 ]; then harness_emit "StopGate" "$(jq -n --arg c "$cmd" '{result:"pass", check:$c}')"; exit 0; fi
blocks=$((blocks + 1)); echo "$blocks" > "$STATE/stop_blocks"
tail_out="$(tail -60 "$STATE/last_check.txt" | head -c 6000)"
harness_emit "StopGate" "$(jq -n --arg c "$cmd" --argjson b "$blocks" --argjson rc "$rc" '{result:"block", check:$c, blocks:$b, rc:$rc}')"
jq -n --arg r "Harness stop gate (block $blocks/2): \`$cmd\` exited $rc in $ROOT. Fix the failures, or if they are pre-existing and unrelated say so explicitly to the user. Output (tail):"$'\n'"$tail_out" '{decision:"block", reason:$r}'
exit 0
