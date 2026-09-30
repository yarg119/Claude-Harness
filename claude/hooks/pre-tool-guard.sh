#!/usr/bin/env bash
# PreToolUse guard (Bash + file edits). Deterministic first; Jev only for the grey zone.
# Output: permissionDecision deny|ask with a reason, or nothing (allow). Always exit 0.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
harness_read_input
[ "${HARNESS_GUARD:-on}" = "off" ] && exit 0
ROOT="$(harness_root)"
[ -f "$ROOT/.claude/state/guard-off" ] && exit 0

VERDICT=""; REASON=""
set_verdict() { # deny beats ask; first reason of the highest severity wins
  if [ "$1" = deny ] && [ "$VERDICT" != deny ]; then VERDICT=deny; REASON="$2"
  elif [ "$1" = ask ] && [ -z "$VERDICT" ]; then VERDICT=ask; REASON="$2"; fi
}
finish() {
  if [ -n "$VERDICT" ]; then
    harness_emit "Guard" "$(jq -n --arg v "$VERDICT" --arg r "$REASON" '{verdict:$v, reason:$r}')"
    harness_pre_decision "$VERDICT" "harness guard: $REASON"
  fi
  exit 0
}

expand_path() { # ~, $HOME, ${HOME}, $TMPDIR; strip quotes
  local p="$1"; p="${p%\"}"; p="${p#\"}"; p="${p%\'}"; p="${p#\'}"
  case "$p" in "~"|"~/"*) p="$HOME${p#\~}";; esac
  p="${p//\$\{HOME\}/$HOME}"; p="${p//\$HOME/$HOME}"
  p="${p//\$\{TMPDIR\}/${TMPDIR:-/tmp}}"; p="${p//\$TMPDIR/${TMPDIR:-/tmp}}"
  printf '%s' "$p"
}

check_rm() { # $1 = segment
  local seg="$1" rec=0 tok
  for tok in $seg; do
    case "$tok" in
      --recursive) rec=1;;
      --*) ;;
      -*[rR]*) rec=1;;
    esac
  done
  [ "$rec" = 1 ] || return 0
  local first=1
  for tok in $seg; do
    [ "$first" = 1 ] && { first=0; continue; }   # skip 'rm'
    case "$tok" in -*) continue;; esac
    local p; p="$(expand_path "$tok")"
    case "$p" in
      *'$'*) set_verdict ask "rm -r with an unexpanded variable in '$tok'"; continue;;
    esac
    case "$p" in
      /|/*'*'|"$HOME"|"$HOME/"|"$HOME/*"|.|..|'*'|./|"$ROOT"|"$ROOT/"|"$H_CWD"|"$H_CWD/") set_verdict deny "rm -r would wipe '$tok' (root, home, project root or cwd)"; continue;;
    esac
    case "$p" in ../*|*/../*|*/..) set_verdict deny "rm -r target '$tok' climbs out of the working directory";; esac
    case "$p" in
      /*)
        case "$p" in
          "$ROOT"/*|"$H_CWD"/*|"${TMPDIR:-/tmp}"*|/tmp/*|/private/tmp/*|/private/var/folders/*|/var/folders/*) ;;
          *) set_verdict deny "rm -r target '$tok' is outside the project and tmp";;
        esac;;
    esac
  done
}

check_git_push() { # $1 = segment
  local seg="$1" force=0 lease=0 tok refs=() branch=""
  [[ "$seg" =~ ^git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+push ]] || return 0
  for tok in $seg; do
    case "$tok" in
      --force-with-lease*) lease=1;;
      --force|-f|-[a-zA-Z]*f*) force=1;;
      +*) force=1; refs+=("${tok#+}");;
      -*|git|push|origin|upstream) ;;
      *) refs+=("$tok");;
    esac
  done
  [ "$force" = 1 ] || [ "$lease" = 1 ] || return 0
  local hit=0 r
  if [ "${#refs[@]}" -gt 0 ]; then
    for r in "${refs[@]}"; do
      [[ "$r" =~ ^(refs/heads/)?([^:]+:)?(main|master)$ ]] && hit=1
      [[ "$r" =~ :(main|master)$ ]] && hit=1
    done
  else
    branch="$(git -C "$ROOT" symbolic-ref --short -q HEAD 2>/dev/null || true)"
    [[ "$branch" =~ ^(main|master)$ ]] && hit=1
  fi
  [ "$hit" = 1 ] || return 0
  if [ "$force" = 1 ]; then set_verdict deny "force-push to main/master is blocked"; else set_verdict ask "force-with-lease to main/master"; fi
}

check_bash() {
  local cmd="$H_CMD" seg
  [ -n "$cmd" ] || return 0
  [[ "$cmd" =~ (curl|wget)[[:space:]][^|]*\|[[:space:]]*(sudo[[:space:]]+)?(sh|bash|zsh)([[:space:]]|$) ]] && set_verdict ask "piping a download into a shell"
  while IFS= read -r seg; do
    seg="${seg#"${seg%%[![:space:]]*}"}"
    seg="${seg#sudo }"
    while [[ "$seg" =~ ^[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+ ]]; do seg="${seg#*[[:space:]]}"; seg="${seg#"${seg%%[![:space:]]*}"}"; done
    [ -n "$seg" ] || continue
    case "$seg" in rm\ *) check_rm "$seg";; esac
    check_git_push "$seg"
    [[ "$seg" =~ ^git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+(reset[[:space:]]+--hard|clean[[:space:]]+-[a-zA-Z]*f|checkout[[:space:]]+--[[:space:]]+\.|restore[[:space:]]+\.|branch[[:space:]]+-D|stash[[:space:]]+(drop|clear)|push[[:space:]]+.*--delete) ]] && set_verdict ask "destructive git operation: '${seg:0:80}'"
    [[ "$seg" =~ (DROP[[:space:]]+(TABLE|DATABASE|SCHEMA)|TRUNCATE[[:space:]]+TABLE|terraform[[:space:]]+(apply|destroy)|kubectl[[:space:]]+delete|docker[[:space:]]+(system[[:space:]]+prune|volume[[:space:]]+rm|rm[[:space:]]+-f)|prisma[[:space:]]+migrate[[:space:]]+reset|supabase[[:space:]]+db[[:space:]]+reset|gh[[:space:]]+repo[[:space:]]+delete|(npm|pnpm|cargo)[[:space:]]+publish) ]] && set_verdict ask "irreversible or remote-state operation: '${seg:0:80}'"
    if [[ "$seg" =~ (^|[[:space:]/\"\'])\.env(\.[A-Za-z0-9_-]+)?([[:space:]\"\']|$) ]] && ! [[ "$seg" =~ \.env\.(example|sample|template|dist) ]]; then set_verdict ask "touches a .env secrets file"; fi
  done < <(printf '%s\n' "$cmd" | sed -E 's/&&|\|\||;|\|/\n/g')
  return 0
}

check_files() {
  local paths=() p b
  if [ "$H_TOOL" = apply_patch ]; then
    while IFS= read -r p; do paths+=("$p"); done < <(printf '%s' "$INPUT" | jq -r '.tool_input | .. | strings' 2>/dev/null | grep -E '^\*\*\* (Update|Add|Delete) File: ' | sed -E 's/^\*\*\* [A-Za-z]+ File: //')
  else
    [ -n "$H_FILE" ] && paths+=("$H_FILE")
  fi
  for p in "${paths[@]}"; do
    b="$(basename "$p")"
    if [[ "$b" =~ ^\.env(\..+)?$ ]] && ! [[ "$b" =~ \.(example|sample|template|dist)$ ]]; then set_verdict deny "editing secrets file '$b' is blocked"; fi
    [[ "$p" =~ /(secrets?|\.secrets)/ ]] && set_verdict deny "editing under a secrets directory is blocked"
    [[ "$b" =~ \.(pem|key|p12|pfx)$|^id_(rsa|ed25519|ecdsa)(\.pub)?$|^(credentials|service-account.*)\.json$|^\.(npmrc|pypirc|netrc)$ ]] && set_verdict deny "editing credential file '$b' is blocked"
    [[ "$b" =~ ^(biome\.jsonc?|\.eslintrc(\..+)?|eslint\.config\..+|\.prettierrc(\..+)?|prettier\.config\..+|\.oxlintrc\.json|oxlint\.config\..+|\.?ruff\.toml|\.?rustfmt\.toml|\.editorconfig|\.stylelintrc(\..+)?|\.golangci\.ya?ml|tsconfig(\..+)?\.json|lefthook\.ya?ml|\.pre-commit-config\.yaml)$ ]] && set_verdict ask "'$b' is a lint/format sensor config. Fix the code, not the sensor; confirm with the user if the config change is intended"
  done
  return 0
}

case "$H_TOOL" in
  Bash) check_bash;;
  Edit|Write|NotebookEdit|MultiEdit|apply_patch) check_files;;
esac
[ -n "$VERDICT" ] && finish

# Grey zone -> Jev tool_risk (fail-open, prints the hook output itself or nothing)
if [ "$H_TOOL" = Bash ] && harness_jev_on && [[ "$H_CMD" =~ (^|[[:space:];&|])(rm|mv|chmod|chown|git[[:space:]]+(push|rebase|reset|clean|filter-branch)|psql|mysql|redis-cli|aws|gcloud|az|gh[[:space:]]+pr[[:space:]]+merge|kubectl|docker|npm[[:space:]]+(unpublish|deprecate)|dd)([[:space:]]|$) ]]; then
  bin="$(harness_bin 2>/dev/null || true)"
  [ -n "$bin" ] && printf '%s' "$INPUT" | harness_run_capped 6 "$bin" jev-hook tool_risk 2>/dev/null || true
fi
exit 0
