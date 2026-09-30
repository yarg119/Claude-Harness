---
name: checkpoint
description: Save durable state to .claude/state/progress.json (goal, done, next, blockers, decisions, commands) so a fresh session or Codex thread can resume. Use at pauses, before /compact, at session end, and when the user asks to save progress or hand off.
argument-hint: "[note for the next session]"
allowed-tools: Read, Bash(git *), Bash(jq *), Write, Edit
---

Write the state a fresh session needs. Note: $ARGUMENTS

1. Read `.claude/state/progress.json` if it exists (create `.claude/state/` otherwise).
2. Merge, never overwrite history:
   ```json
   {"version": 1, "updated_at": "<ISO>", "branch": "<git branch>", "goal": "...",
    "contract": ".claude/state/contract.md", "done": ["..."], "next": ["..."],
    "blockers": ["..."], "decisions": [{"date": "...", "what": "...", "why": "..."}],
    "commands": {"check": "..."}, "uncommitted": ["..."]}
   ```
   `done` is append-only; `next` is replaced; `decisions` append with the why.
3. Keep the file under 60 lines. Detail goes into `docs/exec-plans/` files, linked from `next`.
4. List uncommitted files from `git status --short` and suggest a commit message.
5. If the user wants to continue in Codex, mention `/codex:transfer`.
