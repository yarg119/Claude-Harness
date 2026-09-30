# Advisor (harness)

The advisor is a stronger model (Fable 5.1) that reads this whole conversation, every tool
call included, and returns guidance. It takes no parameters. Claude Code calls it as the
`advisor` tool.

When to call it:
- Before substantive work on a multi-step task. Orientation first (find files, read, fetch),
  then consult, then edit. Writing, editing and committing to an interpretation are
  substantive; `ls`, `grep`, `Read` are not.
- When stuck: the same error twice, an approach not converging, results that do not fit.
- Before declaring done. Make the deliverable durable first (write the file, save, commit),
  then ask "what did I miss?". If the session ended during the call, a durable result persists.
- When considering a change of approach.

How to treat the advice:
- Give it serious weight. If a recommended step fails empirically, or a file contradicts a
  specific claim, adapt and surface the conflict in one more advisor call rather than
  silently switching.
- On short reactive tasks where the next action is dictated by tool output, one call is
  enough; the value is in the first call, before the approach crystallises.
- Subagents inherit the advisor; they may consult it inside their own task.
