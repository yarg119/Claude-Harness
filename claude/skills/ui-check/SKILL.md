---
name: ui-check
description: Visual and guideline check of a web UI change before it is called done. Screenshots the page at phone, tablet and desktop widths in light and dark with playwright-cli, reads them, lists console errors, then audits the changed UI files with the web-interface-guidelines skill. Use after building or changing any page or component, and from /done when UI files changed.
argument-hint: "<url> [files...]"
allowed-tools: Bash(playwright-cli *), Bash(git diff *), Bash(git status *), Bash(lsof *), Read, Glob, Grep, Skill
---

Check a UI change with sensors, not a typecheck. Arguments: $ARGUMENTS

## 1. Target
- Use the URL given. Otherwise find a dev server already listening (`lsof -nP -iTCP -sTCP:LISTEN | grep -E 'node|bun'`) that serves this checkout, and ask if it is ambiguous.
- Never start a server on a port that is in use. If you must start one, pick a free port (e.g. `npx next dev -p 3107`), wait for it, and stop it at the end. Project instructions (CLAUDE.md, AGENTS.md, docs/agents/ui.md) override these defaults; follow them for dev routes such as preview pages that skip auth.

## 2. Screenshot matrix (one named session, closed at the end)
```bash
S=uicheck-$(date +%s); D=.playwright-cli/ui-check; mkdir -p $D
playwright-cli -s=$S open <url>
playwright-cli -s=$S resize 390 844;  playwright-cli -s=$S set-color-scheme light; playwright-cli -s=$S screenshot --filename=$D/phone-light.png
playwright-cli -s=$S set-color-scheme dark;  playwright-cli -s=$S screenshot --filename=$D/phone-dark.png
playwright-cli -s=$S resize 820 1180; playwright-cli -s=$S set-color-scheme light; playwright-cli -s=$S screenshot --filename=$D/tablet-light.png
playwright-cli -s=$S set-color-scheme dark;  playwright-cli -s=$S screenshot --filename=$D/tablet-dark.png
playwright-cli -s=$S resize 1440 900; playwright-cli -s=$S set-color-scheme light; playwright-cli -s=$S screenshot --filename=$D/desktop-light.png
playwright-cli -s=$S set-color-scheme dark;  playwright-cli -s=$S screenshot --filename=$D/desktop-dark.png
playwright-cli -s=$S console warning
```
- Run commands one per line as above (zsh does not word-split variables). Add `--full-page` for long pages.
- If the app switches theme with a class instead of `prefers-color-scheme`, toggle it the way the app does (its theme control, or `playwright-cli -s=$S eval "document.documentElement.classList.toggle('dark')"`) and say which you used.
- **Read every screenshot** with the Read tool. Look for overflow and clipping, horizontal scroll, misalignment, contrast, unreadable dark-mode colours, missing focus or hover feedback, and broken empty/loading/error states. Use `snapshot`, `click`, `fill` and `route` (mocking) to reach the states the change touches.
- `playwright-cli -s=$S close` when done; stop any server you started.

## 3. Guidelines audit of the changed files
- Files: the ones passed in, else `git diff --name-only HEAD -- '*.tsx' '*.jsx' '*.css' '*.html' '*.vue' '*.svelte'` plus untracked UI files from `git status --short`.
- Invoke the `web-interface-guidelines` skill on them. Fix real findings or say why one does not apply (project copy and design conventions win over the guideline's copy-style rules).

## 4. Report
- A table of screenshots (path, viewport, theme) and what you saw in each.
- Console errors and warnings worth fixing.
- Guideline findings as `file:line - issue`, marked fixed / not applicable.
- Verdict: ready, or what must change. Screenshots stay in `.playwright-cli/` (gitignore it).
