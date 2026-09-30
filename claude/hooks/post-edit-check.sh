#!/usr/bin/env bash
# PostToolUse (Edit|Write): mark the turn as edited, auto-format, lint, feed diagnostics back.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
harness_read_input
STATE="$(harness_state_dir)"; ROOT="$(harness_root)"
paths=()
if [ "$H_TOOL" = apply_patch ]; then
  while IFS= read -r p; do paths+=("$p"); done < <(printf '%s' "$INPUT" | jq -r '.tool_input | .. | strings' 2>/dev/null | grep -E '^\*\*\* (Update|Add) File: ' | sed -E 's/^\*\*\* [A-Za-z]+ File: //')
else
  [ -n "$H_FILE" ] && paths+=("$H_FILE")
fi
[ "${#paths[@]}" -gt 0 ] || exit 0
for p in "${paths[@]}"; do
  case "$p" in /*) ;; *) p="$ROOT/$p";; esac
  printf '%s\n' "$p" >> "$STATE/edited"
  grep -qxF "$p" "$STATE/edited.all" 2>/dev/null || printf '%s\n' "$p" >> "$STATE/edited.all"
done
harness_emit "Edit" "$(printf '%s\n' "${paths[@]}" | jq -R . | jq -cs '{files:.}')"

f="${paths[0]}"; case "$f" in /*) ;; *) f="$ROOT/$f";; esac
[ -f "$f" ] || exit 0
[[ "$f" =~ /(node_modules|\.git|dist|build|\.next|target|vendor|\.venv)/ ]] && exit 0
ext="${f##*.}"; rel="${f#"$ROOT"/}"
before="$(mktemp)"; cp "$f" "$before" 2>/dev/null || exit 0
out=""; rc=0; ran=""
run_tool() { # $1 label, rest = command
  local label="$1"; shift
  local o; o="$( cd "$ROOT" && harness_run_capped 25 "$@" 2>&1 )"; local r=$?
  ran="${ran}${label} "
  if [ "$r" -ne 0 ]; then rc=1; out="${out}${label} (exit $r):"$'\n'"$(printf '%s' "$o" | head -40)"$'\n'; fi
}
custom_fmt="$(jq -r '.format // empty' "$ROOT/.claude/harness.json" 2>/dev/null)"
custom_lint="$(jq -r '.lint // empty' "$ROOT/.claude/harness.json" 2>/dev/null)"
if [ -n "$custom_fmt" ]; then run_tool format bash -lc "${custom_fmt//\{file\}/$rel}"; fi
if [ -n "$custom_lint" ]; then run_tool lint bash -lc "${custom_lint//\{file\}/$rel}"; fi
if [ -z "$custom_fmt$custom_lint" ]; then
  case "$ext" in
    js|jsx|ts|tsx|mjs|cjs|mts|cts|json|jsonc|css|scss|md|mdx|yaml|yml|html|vue|svelte|astro|graphql)
      if [ -f "$ROOT/biome.json" ] || [ -f "$ROOT/biome.jsonc" ]; then
        b="$(harness_tool_bin "$ROOT" biome)"; [ -n "$b" ] && run_tool biome "$b" check --write "$rel"
      else
        if [ -f "$ROOT/.prettierrc" ] || ls "$ROOT"/.prettierrc.* "$ROOT"/prettier.config.* >/dev/null 2>&1 || jq -e '.prettier' "$ROOT/package.json" >/dev/null 2>&1; then
          b="$(harness_tool_bin "$ROOT" prettier)"; [ -n "$b" ] && run_tool prettier "$b" --write --ignore-unknown --log-level warn "$rel"
        fi
        case "$ext" in js|jsx|ts|tsx|mjs|cjs|mts|cts|vue|svelte|astro)
          if ls "$ROOT"/.oxlintrc.json "$ROOT"/oxlint.config.* >/dev/null 2>&1; then b="$(harness_tool_bin "$ROOT" oxlint)"; [ -n "$b" ] && run_tool oxlint "$b" "$rel"; fi
          if ls "$ROOT"/eslint.config.* "$ROOT"/.eslintrc* >/dev/null 2>&1; then b="$(harness_tool_bin "$ROOT" eslint)"; [ -n "$b" ] && run_tool eslint "$b" --fix --no-warn-ignored "$rel"; fi;;
        esac
      fi;;
    py)
      b="$(harness_tool_bin "$ROOT" ruff)"; [ -n "$b" ] && { run_tool "ruff format" "$b" format "$rel"; run_tool "ruff check" "$b" check --fix "$rel"; };;
    go) command -v gofmt >/dev/null && run_tool gofmt gofmt -l -w "$rel";;
    rs) command -v rustfmt >/dev/null && run_tool rustfmt rustfmt --edition 2021 "$rel";;
  esac
fi
changed=0; cmp -s "$before" "$f" || changed=1
rm -f "$before"
msg=""
[ "$rc" -ne 0 ] && msg="harness post-edit: diagnostics for $rel"$'\n'"$(printf '%s' "$out" | head -c 3000)"
[ "$changed" = 1 ] && msg="${msg:+$msg$'\n'}harness post-edit: $rel was auto-formatted on disk (${ran% }). Re-read it before further edits."
if [ -n "$msg" ]; then harness_emit "Lint" "$(jq -n --arg r "$rel" --argjson rc "$rc" --argjson ch "$changed" '{file:$r, rc:$rc, changed:$ch}')"; harness_ctx PostToolUse "$msg"; fi
exit 0
