---
name: done
description: Definition-of-done pass. Run before telling the user a task is complete. Runs the check command, an adversarial second pass (Codex when switched on, otherwise the reviewer subagent), an advisor consult, and a checkpoint. Also use when the user says "done", "wrap up" or "is this finished".
argument-hint: "[what was delivered]"
allowed-tools: Read, Glob, Grep, Bash, Agent, Skill, Write, Edit
---

Prove the work is done before saying so. Delivered: $ARGUMENTS

1. State: `git status --short` and `git diff --stat`. Read `.claude/state/contract.md` if it exists.
2. Sensors: run the check command (`$HARNESS_CHECK_CMD`, else `.claude/harness.json` `check`, else the discovered one). Paste the tail. A failing check means not done.
3. Second pass:
   - Run `harness config codex` (or read `~/.claude/harness/config.json`). If Codex is on, run `/codex:adversarial-review --wait` and keep its output verbatim.
   - Otherwise run the `reviewer` subagent on the diff.
   - Fix blockers and majors, or list them with a reason for leaving them.
4. Advisor: consult the advisor with the contract, the diff summary and the findings. Ask one question: "what would make this not done?" Act on the answer.
5. Checkpoint: run `/checkpoint` with a one-line note.
6. Report against the contract's acceptance criteria, one line each, marked pass or fail with the evidence (command and output tail). Never mark pass without evidence in this transcript.
