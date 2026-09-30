---
name: harness
description: Show the harness status: model tree, advisor, effort, toggles (codex, jev), hook health and the check command. Use when the user asks how the harness is configured or whether it is working.
allowed-tools: Bash(harness *), Bash(jq *), Read
---

Run `harness doctor` and present its output as-is. If the `harness` binary is missing, read `~/.claude/settings.json` (`model`, `advisorModel`, `modelSettings`, `hooks`) and `~/.claude/harness/config.json` and summarise the tree, then say the CLI is not installed (`uv tool install --editable <repo>`).
