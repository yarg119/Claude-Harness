#!/usr/bin/env bash
# Status line: prints one line and mirrors the JSON payload for the harness dashboard.
set -u
HARNESS_HOME="${HARNESS_HOME:-$HOME/.claude/harness}"
input="$(cat 2>/dev/null || true)"; [ -n "$input" ] || exit 0
IFS=$'\x1f' read -r sid model effort ctx cost dur h5 d7 dir agent sname fast <<< "$(printf '%s' "$input" | jq -r '[
  (.session_id // ""), (.model.display_name // .model.id // "?"), (.effort.level // ""),
  (.context_window.used_percentage // "" | tostring), (.cost.total_cost_usd // "" | tostring), (.cost.total_duration_ms // "" | tostring),
  (.rate_limits.five_hour.used_percentage // "" | tostring), (.rate_limits.seven_day.used_percentage // "" | tostring),
  (.workspace.current_dir // ""), (.agent.name // ""), (.session_name // ""), (.fast_mode // false | tostring)
] | join("\u001f")' 2>/dev/null)"
if [ -n "$sid" ]; then mkdir -p "$HARNESS_HOME/status" 2>/dev/null && printf '%s' "$input" > "$HARNESS_HOME/status/$sid.json" 2>/dev/null; fi
cfg="$HARNESS_HOME/config.json"
codex="$(jq -r 'if .codex == true then "on" else "off" end' "$cfg" 2>/dev/null || echo off)"
jev="$(jq -r 'if .jev == true then "on" else "off" end' "$cfg" 2>/dev/null || echo off)"
adv="$(jq -r '.advisorModel // "off"' "$HOME/.claude/settings.json" 2>/dev/null || echo off)"
R=$'\e[0m'; B=$'\e[1m'; O=$'\e[38;5;209m'; BL=$'\e[38;5;110m'; G=$'\e[38;5;114m'; Y=$'\e[38;5;221m'; RD=$'\e[38;5;203m'; D=$'\e[2m'
ctxc="$G"; [ -n "$ctx" ] && [ "${ctx%.*}" -ge 70 ] 2>/dev/null && ctxc="$Y"; [ -n "$ctx" ] && [ "${ctx%.*}" -ge 85 ] 2>/dev/null && ctxc="$RD"
line="${B}${O}${model}${R}"
[ -n "$effort" ] && line="$line ${D}·${R} ${effort}"
[ -n "$ctx" ] && line="$line ${D}|${R} ctx ${ctxc}${ctx%.*}%${R}"
if [ -n "$cost" ]; then mins=""; [ -n "$dur" ] && mins="$(( ${dur%.*} / 60000 ))m"; line="$line ${D}|${R} \$$(printf '%.2f' "$cost" 2>/dev/null || echo "$cost") $mins"; fi
[ -n "$h5" ] && line="$line ${D}|${R} 5h ${h5%.*}% 7d ${d7%.*}%"
if [ -n "$dir" ]; then br="$(git -C "$dir" symbolic-ref --short -q HEAD 2>/dev/null || true)"; line="$line ${D}|${R} $(basename "$dir")${br:+ ${BL}($br)${R}}"; fi
line="$line ${D}|${R} adv:${adv} jev:${G}${jev}${R} codex:${codex}"
[ -n "$agent" ] && line="$line ${BL}[agent:$agent]${R}"
[ "$fast" = "true" ] && line="$line ${Y}[fast]${R}"
printf '%s\n' "$line"
