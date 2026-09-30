#!/usr/bin/env bash
# Agent-scoped PreToolUse guard for explorer/reviewer: Bash is read-only.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
harness_read_input
[ "$H_TOOL" = Bash ] || exit 0
cmd="$H_CMD"
deny() { harness_pre_decision deny "explorer/reviewer are read-only: $1. Report the command for the main session to run."; exit 0; }
[[ "$cmd" =~ (\>|\>\>|[[:space:]]tee[[:space:]]|sed[[:space:]]+-i|-delete|-exec|xargs|(^|[[:space:];&|])(rm|mv|cp|chmod|chown|touch|mkdir|npm[[:space:]]+(i|install|ci)|pnpm[[:space:]]+(i|install|add)|pip[[:space:]]+install|uv[[:space:]]+(add|pip)|git[[:space:]]+(add|commit|push|checkout|switch|reset|rebase|merge|stash|clean|rm|mv|tag[[:space:]]+-|branch[[:space:]]+-)) ) ]] && deny "'${cmd:0:80}' writes or mutates"
while IFS= read -r seg; do
  seg="${seg#"${seg%%[![:space:]]*}"}"; [ -n "$seg" ] || continue
  while [[ "$seg" =~ ^[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+ ]]; do seg="${seg#*[[:space:]]}"; done
  first="${seg%% *}"
  case "$first" in
    git) [[ "$seg" =~ ^git[[:space:]]+(log|show|blame|diff|status|branch|rev-parse|ls-files|grep|shortlog|describe|tag|remote|config[[:space:]]+--get|worktree[[:space:]]+list|stash[[:space:]]+list)([[:space:]]|$) ]] || deny "'${seg:0:80}' is not a read-only git command";;
    ls|wc|head|tail|cat|find|rg|grep|egrep|fgrep|tree|stat|file|du|df|jq|yq|sort|uniq|cut|awk|sed|echo|printf|pwd|which|type|env|printenv|date|basename|dirname|realpath|readlink|xxd|od|strings|diff|comm|column|tr|true|test|\[|node|python3|python|go|cargo|npm|pnpm|bun|uv|npx|bunx|ctx7|gh|curl|wget|man|less|more|tsc|eslint|ruff|pytest|mypy|make) ;;
    *) deny "'$first' is not on the read-only allowlist";;
  esac
  case "$first" in
    node|python3|python|go|cargo|npm|pnpm|bun|uv|npx|bunx|gh|make)
      [[ "$seg" =~ ^(node|python3|python)[[:space:]]+-[ce][[:space:]] ]] && deny "inline scripts are not allowed for read-only agents"
      [[ "$seg" =~ ^(npm|pnpm|bun)[[:space:]]+(run|test|exec|x)[[:space:]] ]] && deny "'${seg:0:60}' may write";;
  esac
done < <(printf '%s\n' "$cmd" | sed -E 's/&&|\|\||;|\|/\n/g')
exit 0
