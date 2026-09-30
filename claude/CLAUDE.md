# Harness (global map)

Model tree: Opus 5.5 at high effort runs this session and makes the decisions. Sonnet 5.5
subagents at medium effort do the routine work: `explorer` reads code, `worker` edits and
runs tests, `researcher` pulls docs, `reviewer` hunts bugs. Fable 5.1 is on call as the
advisor. Codex (`/codex:*`) is a second opinion only while the harness has it switched on
(see the `[harness] toggles` line injected at session start).

## Operating loop
1. Read the `[harness]` context injected at session start: branch, commits, check command,
   contract, progress, toggles.
2. Multi-file or long work: run `/plan-contract` first and get sign-off. A bounded contract
   (deliverable, constraints, non-goals, acceptance criteria) decides when work is done.
3. Delegate routine work and keep this context for planning and decisions.
   Details: `~/.claude/rules/harness-delegation.md`.
4. Consult the advisor before substantive work, when stuck, and before declaring done.
   Details: `~/.claude/rules/harness-advisor.md`.
5. Sensors before claims: run the check command and paste its output. Never say "done",
   "passing" or "fixed" without evidence from a tool result.
   Details: `~/.claude/rules/harness-verification.md`.
6. `/done` before declaring a task complete. `/checkpoint` at pauses and before `/compact`.
   `/gc` before committing.

## Durable state (the repo is the system of record)
- `.claude/state/contract.md` current bounded contract.
- `.claude/state/progress.json` goal, done, next, blockers, decisions. Commit it with the work.
- `.claude/harness.json` project overrides: `check`, `format`, `lint`, `stopGate`.
- `HARNESS.md` contract template; `docs/` for architecture and execution plans.

## Never
- Work around a hook, disable it, or edit a lint/format config to make a sensor pass.
  If a hook blocks you, fix the cause or ask the user.
- Set `CLAUDE_CODE_EFFORT_LEVEL` (it overrides subagent effort) or turn the advisor off.
- Put secrets in context or in instruction files.
- Grow instruction files past a map: pitfalls and conventions go in, anything derivable
  from the code stays out.
