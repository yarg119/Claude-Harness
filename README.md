# Claude Harness

An installable harness for running Claude Code (and, when switched on, Codex) from the
terminal, plus a live **agent-tree dashboard** that embeds `claude` in a PTY pane.

```
Opus 5.5 · high        main session: plans + decides
  ├─ explorer          Sonnet 5.5 · medium   read code
  ├─ worker            Sonnet 5.5 · medium   edit + run tests
  ├─ researcher        Sonnet 5.5 · medium   look up docs (context7)
  ├─ reviewer          Sonnet 5.5 · medium   adversarial second pass
  ├─ Fable 5.1         on call as /advisor: before a plan · when an error repeats · before done
  ├─ Jev               fork layer: which worker · tool risk · retry-or-stop (sharp → code, split → Opus)
  └─ Codex             optional: /codex:adversarial-review in /done, /codex:rescue on demand
```

Plan on high. Delegate on medium. Keep Fable on call.

## What gets installed

| Where | What |
| - | - |
| `~/.claude/settings.json` (merged, backed up) | `model: opus`, `advisorModel: fable`, per-model effort (`modelSettings`), status line, permissions, hooks |
| `~/.claude/agents/` | `explorer`, `worker`, `researcher`, `reviewer` (all `sonnet` / `effort: medium`) |
| `~/.claude/skills/` | `/plan-contract`, `/done`, `/checkpoint`, `/gc`, `/harness` |
| `~/.claude/rules/` | delegation, advisor, verification rules (short, map-style) |
| `~/.claude/hooks/` | guard (deny/ask), post-edit format+lint, stop gate, session context, failure counter, event emitters |
| `~/.claude/HARNESS.md` + one import line in `~/.claude/CLAUDE.md` | the global map (≤40 lines) |
| `~/.codex/` (with `--with-codex`) | `hooks.json` (same scripts), `harness.config.toml` profile, a delimited block in `AGENTS.md` |
| `~/.claude/harness/` | runtime state: `config.json`, `events/`, `sessions/`, `status/`, `jev/`, `state/`, `backups/` |

Everything except merged files is a symlink into this repo, so editing the repo edits the install.

## Install

```bash
cd ~/Desktop/Claude-Harness
uv tool install --editable .          # puts `harness` on ~/.local/bin (hooks call it for Jev)
harness install --with-codex          # add --dry-run first to preview; --keep-puppetmaster to keep its hooks
harness doctor
```

One-time steps Claude Code needs from you:
1. Fable consent: if you have already run a session on Fable (`/model fable`) the usage-credits
   consent is granted and `advisorModel: fable` is live; otherwise run `/model fable` once, accept,
   and switch back. Without it the setting is silently not applied.
2. For Codex: open `codex`, run `/hooks`, and trust the harness hooks (hash-pinned). Re-trust after
   editing a hook script. `harness codex off` disables the plugin and the `/done` second pass.
3. For Jev, one key in your shell (or in `~/.claude/harness/env`, `chmod 600`), then
   `harness jev on && harness jev test`:
   - `AI_GATEWAY_API_KEY=vck_...` routes through Vercel AI Gateway (`typesafe-ai/jev`), or
   - `TYPESAFE_API_KEY=ts_...` calls TypeSafe directly, or `OPENROUTER_API_KEY` for OpenRouter.

Note: `model: "opus"` is now the global default, so new sessions start on Opus 5.5; `/model` still
switches per session, and `harness run --1m` launches `opus[1m]`.

First-session checks worth doing once:
- Ask for a broad exploration and confirm the `explorer` box turns "running" in the dashboard.
- Ask the explorer to run `git commit`; its read-only guard should deny it.
- Break a test, say "done", and watch the stop gate block once with the failing output.

## Run

```bash
harness                     # launcher: resume one of your 5 latest sessions, or start a new one
                            #   (here, or in a new git worktree branched from a base you pick)
harness run --new           # skip the launcher: new session in the current directory
harness run --1m            # opus[1m]
harness run -C ~/Documents/Projects/Verax   # start claude in another repo
harness run -- --resume     # anything after -- goes to claude (e.g. -- -w my-feature for a new worktree)
harness attach              # dashboard only, watching the latest session (e.g. in a second tab)
harness run --layout tmux   # fallback: claude left, dashboard right
```

Keys: `F1` help · `F2` show/hide the claude pane · `F3` claude full screen · `F10` quit (also ends claude).
Scrolling the claude pane: mouse wheel / trackpad, `PgUp`/`PgDn` (`Fn+↑`/`Fn+↓` on a MacBook), and
`Ctrl+O` for transcript mode with `/` search. The pane always runs Claude Code's fullscreen renderer
(`CLAUDE_CODE_NO_FLICKER=1`) because that renderer scrolls in-app; the embedded emulator keeps no scrollback.
On terminals 160+ columns wide, F2 puts claude beside the tree; narrower ones flip between them.
Typing while the tree is showing brings claude up. The main box and command bar turn yellow with
"claude is waiting → F2" when claude needs input. The layout scales from 90×46 up to full screen;
shorter windows scroll the tree while the status bars stay pinned.

## Toggles

```bash
harness codex on|off        # enables/disables the codex plugin and the /done second pass
harness jev on|off|test     # Jev fork layer (needs a key)
harness config              # show ~/.claude/harness/config.json
harness init <repo>         # drop the project template (AGENTS.md, CLAUDE.md, HARNESS.md, .claude/harness.json, docs/)
harness events -f           # tail the hook event stream
```

## How the pieces enforce the workflow

- **Bounded contracts**: `/plan-contract` writes `.claude/state/contract.md`; `/done` reports against it.
- **Sensors before claims**: the stop gate runs the project's check command when files changed and
  blocks at most twice per session; post-edit hooks format and lint every edited file.
- **Dual encoding**: every rule in `HARNESS.md` has a mechanical twin in `claude/hooks/`.
- **Advisor**: `HARNESS.md` and `rules/harness-advisor.md` tell Opus when to consult Fable
  (adapted from Anthropic's suggested advisor prompt). The dashboard counts calls and tokens read.
  Fable returns encrypted advice, so the panel shows the sentence Opus wrote right after applying it.
- **Jev**: `route` (UserPromptSubmit), `tool_risk` (PreToolUse Bash grey zone), `retry_or_stop`
  (third identical failure). Sharp decisions (p ≥ 0.80, configurable) act; split ones defer to Opus.
- **Durable state**: `.claude/state/progress.json` via `/checkpoint`; git log is the bridge.

## What is verified and what is not

Verified: hook gates (deny/ask/allow, stop gate twice-then-cap, failure counter), settings merge
idempotency, `harness doctor` 48/48, hook events from a live headless session, and real Claude
Code rendering its startup screen inside the embedded pane with the tree beside it. Not yet exercised
by tests: keystroke passthrough in a long interactive session and the `~` expansion in subagent
frontmatter hooks (see the first-session checks). Fallbacks: `harness attach`, `--layout tmux`.

## Uninstall

`harness uninstall` removes the symlinks and harness hook groups; backups live in
`~/.claude/harness/backups/<timestamp>/`.

## Development

```bash
uv sync --all-groups && uv run pytest -q
```
