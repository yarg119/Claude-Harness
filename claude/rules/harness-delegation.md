# Delegation (harness)

Keep the main session's context for planning, decisions and review. Send the routine work out.

| Need | Subagent | Returns |
| - | - | - |
| Where is X, what calls Y, how does Z work | `explorer` (read-only) | findings with `path:line`, entry points, data flow, unknowns |
| Library API, version, migration, config option | `researcher` (read-only, context7/WebFetch) | exact snippet, version, source URLs, confidence |
| A well-specified change with acceptance criteria | `worker` (edits, runs the check command) | files changed, commands run with exit codes, remaining failures |
| Second pass on a diff | `reviewer` (read-only, adversarial) or `/codex:adversarial-review` when Codex is on | findings by severity with `path:line` and a verification step |

Rules:
- Give every subagent a bounded prompt: goal, files in scope, constraints, the exact return
  format. Vague prompts produce vague results and burn medium-effort tokens.
- Run independent subagents in parallel (one message, several `Agent` calls).
- Do not delegate one-line edits or single-file lookups; do them inline.
- Do not delegate decisions. Subagents report; this session decides.
- Plugin agents (`feature-dev:*`, `codex:codex-rescue`) pin Sonnet but carry no `effort`,
  so they inherit this session's high effort. Prefer the harness agents for routine work.
