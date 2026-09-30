<!-- claude-harness:begin -->
# Harness (shared with Claude Code)

- The repo is the system of record: read `.claude/state/progress.json`, `.claude/state/contract.md`
  and `git log --oneline -10` before starting. Write progress back before stopping.
- Bounded contract before multi-file work: deliverable, in-scope files, constraints, non-goals,
  acceptance criteria as runnable checks. `HARNESS.md` in the repo is the template.
- Sensors decide, not confidence: run the check command from `.claude/harness.json` (`check`)
  and paste the output before claiming anything passes.
- Hooks are active (guard, post-edit format+lint, stop gate). If one blocks you, fix the cause
  or ask the user; never edit a lint/format config or a secrets file to get past it.
- Second pass before done: `codex review --uncommitted`, then fix blockers.
- Keep instruction files short: pitfalls and conventions in, anything derivable from code out.
<!-- claude-harness:end -->
