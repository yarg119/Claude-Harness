# Verification and enforcement (harness)

Sensors decide, not confidence. A claim of success needs a tool result in this transcript.

Sensors:
- Check command: from `.claude/harness.json` `check`, else discovered (package.json
  `check`/`typecheck`/`test`, `pytest -x -q`, `go test`, `cargo check`, `make check`).
  It is exported as `HARNESS_CHECK_CMD` and shown in the session-start context.
- Formatter and linter run on every edited file (post-edit hook) and report back. When the
  hook says a file was auto-formatted, re-read it before the next edit.
- Type checker and tests are the acceptance criteria of a contract. Add a test when a bug
  is found; a test resists rot better than a note.

Mechanical gates (dual-encoding: the rule above, the hook below):
- Guard denies `rm -r` outside the project/tmp, force-push to main/master, and edits to
  `.env*`, secrets or credential files. It asks on destructive git, DROP/TRUNCATE,
  terraform/kubectl, lint-config edits and `curl | sh`.
- Stop gate runs the check command when files changed this turn. It blocks at most twice
  per session and shows the failing output. Fix the failure or tell the user it is
  pre-existing and unrelated.
- Repeated identical tool failures (3x) inject a reminder to stop retrying and consult the
  advisor.

Definition of done (`/done`): check command passes, diff matches the contract's acceptance
criteria, a second pass found no blockers, the advisor was asked what is missing, and
`progress.json` is updated.
