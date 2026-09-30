---
name: plan-contract
description: Write a bounded work contract (deliverable, in-scope files, constraints, non-goals, acceptance criteria, sensors) before any multi-file or long task, and get user sign-off. Use when asked to plan or before starting big work.
argument-hint: "<task in one or two sentences>"
allowed-tools: Read, Glob, Grep, Bash(git *), Agent, AskUserQuestion, Write, Edit
---

Turn the request into a bounded contract, then get sign-off. Task: $ARGUMENTS

1. Orient. Use `explorer` for what you do not know about the code (at most two calls, parallel). Read `.claude/state/progress.json` and `HARNESS.md` if present.
2. Draft the contract with these sections, each concrete enough to verify:
   - Deliverable: exact files, formats, behaviours.
   - In-scope files.
   - Constraints: dependencies allowed, style, budget.
   - Non-goals: what must not be touched.
   - Acceptance criteria: runnable checks (commands, expected outputs, tests to add).
   - Sensors: the check command that proves it.
   - Risks and rollback.
3. If the change touches more than five files or adds a dependency, consult the advisor with the draft before asking the user.
4. Ask the user for sign-off with `AskUserQuestion` (approve / change scope / cancel). Do not edit code before approval.
5. Write the approved contract to `.claude/state/contract.md` (create the directory if needed) and print the first implementation step.
