#!/usr/bin/env bash
# Generic observer: appends one event line for the dashboard. Never blocks.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
harness_read_input
extra="$(printf '%s' "$INPUT" | jq -c '{
  stop_reason: (.stop_reason // null),
  last: ((.last_assistant_message // "") | .[0:240]),
  notification: (.notification_type // .type // null),
  message: ((.message // "") | .[0:240]),
  prompt: ((.prompt // .user_input // "") | .[0:240]),
  from_model: (.from_model // null), to_model: (.to_model // null),
  compaction_type: (.compaction_type // null),
  file: (.tool_input.file_path // .tool_input.path // null),
  cmd: ((.tool_input.command // "") | .[0:200]),
  desc: ((.tool_input.description // "") | .[0:120]),
  subagent_type: (.tool_input.subagent_type // null),
  ok: (if .hook_event_name == "PostToolUseFailure" then false else null end)
} | with_entries(select(.value != null and .value != ""))' 2>/dev/null || echo '{}')"
harness_emit "$H_EVENT" "$extra"
exit 0
