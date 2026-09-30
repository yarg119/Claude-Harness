# <project name>

One paragraph: what this is, who uses it, what "working" means.

## Commands
- check: `<typecheck && fast tests>`   (mirrors `.claude/harness.json` "check")
- test: `<full test suite>`
- dev: `<run locally>`
- lint / format: `<tools>`

## Layout (map, not manual)
- `src/` ...
- `tests/` ...
- `docs/ARCHITECTURE.md` domains, layers and dependency direction
- `docs/exec-plans/` active and completed execution plans; `.claude/state/progress.json` current state

## Conventions and pitfalls
- <things a new engineer would get wrong on day one>

## Definition of done
Check command passes, diff matches `.claude/state/contract.md`, second pass has no blockers,
`progress.json` updated. In Claude Code run `/done`; in Codex run `codex review --uncommitted`.
