#!/usr/bin/env bash
# PreCompact: snapshot durable facts so session-start (source=compact) can re-inject them.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
harness_read_input
STATE="$(harness_state_dir)"; ROOT="$(harness_root)"
{
  echo "snapshot $(date -u +%FT%TZ) trigger=${H_TRIGGER:-?}"
  echo "git status:"; git -C "$ROOT" status --short 2>/dev/null | head -50
  echo "diff stat: $(git -C "$ROOT" diff --stat 2>/dev/null | tail -1)"
  echo "edited this session:"; sort -u "$STATE/edited.all" 2>/dev/null | head -50
  [ -f "$STATE/last_check.txt" ] && { echo "last check (head):"; head -5 "$STATE/last_check.txt"; }
  [ -f "$ROOT/.claude/state/contract.md" ] && echo "contract: .claude/state/contract.md"
} > "$STATE/precompact.txt" 2>/dev/null || true
harness_emit "PreCompact" "$(printf '%s' "$INPUT" | jq -c '{trigger:(.trigger // .compaction_type // null)}')"
exit 0
