---
name: gc
description: Garbage-collection pass over this session's changes. Removes debug output, dead code, stray temp files, stale TODOs, duplicated helpers, and outdated progress entries. Run after /done or before a commit.
allowed-tools: Read, Glob, Grep, Edit, Write, Bash(git *), Bash(rm *), Agent
---

Pay down the small debt now, while it is cheap.

1. Scope: files changed since the session started (`git diff --name-only $(cat "$HARNESS_STATE_DIR/start_commit" 2>/dev/null || echo HEAD~5)..HEAD` plus the working tree).
2. Checklist, in each file: `console.log`/`print`/`debugger` left behind, commented-out code, unused imports or exports, helpers that duplicate an existing utility, temp files, TODOs without an owner or ticket, `progress.json` `next` items that are already done.
3. Make each removal a separate, obvious edit. List every one in the report.
4. Re-run the check command at the end and paste the tail. If it fails, revert the last removal and say so.
5. Do not refactor beyond the checklist; propose larger cleanups as `next` items instead.
