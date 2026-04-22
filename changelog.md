# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- `helpers.js`: single-source helper library (COLOR, SPACE, RADIUS, TYPE, loadFont, solid, frame, row, col, text, ICONS, icon). Auto-prepended to every user script by `bin/figma-run`; user scripts no longer paste it inline. Includes a runtime token guard that throws on raw pixel literals for pad/gap and an auto-cleanup of stray 100×100 unnamed rectangles on the current page.
- `profiles/{ios,material,neutral}.json`: shipped design presets for the mandatory profile JSON. Selected via `/tmp/claude-figma.profile.json` (e.g. `{"preset": "ios"}` or full `{"preset": "custom", ...}`).
- `row()` / `col()` helpers — thin wrappers around `frame` with sensible default alignment/gaps.
- `bin/figma-run --raw` flag: bypass helper+profile prepending for internal probes and the smoketest.
- `run.py` `open_quick_actions(page)` + `_reset_tool(page)` + `click_canvas_safe(page, x, y)` helpers: verify Quick Actions focus before typing; force Move tool (Escape + V) before any canvas-area mouse click. Eliminates the "R from Scripter → 100×100 rectangle" keystroke-leak bug.
- `manual/USAGE.md`: Comprehensive user manual for project utilization.
- `GEMINI.md`: Project context and instructions for Gemini-based agents.
- `changelog.md`: Initial version of the project changelog.

### Changed
- `bin/figma-run`: removed the STATUS=timeout auto-restart. On any non-ok status, prints the last 30 lines of `/tmp/claude-figma.log` and exits non-zero. Claude is now expected to stop and report to the user on failure — never loop-restart.
- `bin/figma-run`: refuses to run when `/tmp/claude-figma.profile.json` is missing. Claude must call `AskUserQuestion` for font / colors / spacing / radius / typography and write the resolved profile first.
- `run.py` `scripter_exec`: removed the one-reopen retry on editor-write failure. First-attempt failure → `STATUS=error`, no further Scripter popups.
- `run.py` `open_plugin` / `reopen_scripter` / initial `serve()` Scripter open: each attempt now verifies Quick Actions opened (input gained focus) before typing the plugin name. Never types on a bare canvas.
- `run.py` `close_scripter`: bounding-box close click now routes through `click_canvas_safe` (Escape + V first).
- `SKILL.md`: shrunk to the API surface + ask-first workflow. No more 170-line helper paste requirement. New mandatory "design profile" step lists the five `AskUserQuestion` prompts.
- `CLAUDE.md`: new "Design profile" and "Failure policy" sections; updated "Known issues" with the 100×100 keystroke-leak story and the new guards; code style no longer requires inline helper pasting.
- `bin/figma-run-smoketest`: uses `--raw` so the IPC round-trip test does not require a profile.
- Skill dir symlinks (`scripter.md`, `add-component.md`, `figma-comments.md`, `pdf-import.md`): repointed from the stale `ClaudeProjects/.../session-logs-update/claude-to-figma-scripter/` path to the authoritative `/Users/ivan/vibe/claude-to-figma-scripter/` copies.
