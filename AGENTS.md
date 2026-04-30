# Agent Instructions — claude-to-figma-scripter

Tool-agnostic workflow for any LLM-driven coding assistant (Claude Code, Cursor, Aider, Windsurf, Continue.dev, Copilot agent, custom API clients, etc.) that wants to drive Figma designs via code.

**Trigger whenever** the user mentions a Figma URL (`figma.com/design/…` or `figma.com/file/…`) or any phrasing about creating, modifying, inspecting, or iterating a Figma design — "create a component", "update the token", "add a button to the page", etc.

This file is the single public source of agent instructions. Do not add parallel
agent-specific instruction files; point every tool or model at `AGENTS.md`
instead.

---

## What this project is

A persistent Playwright/Firefox session logged into Figma with the Scripter plugin open. You write Figma Plugin API JavaScript; the harness pastes it into Scripter and clicks Run; the effect appears on the Figma canvas.

Core technologies: Python 3.10+, Playwright Firefox, JavaScript, and the Figma
Plugin API.

The harness lives at the **project root** (the directory containing `run.py`).

All `run.py` calls below use paths relative to the project root (`./`).

---

## Environment map

```text
python      = ./.venv/bin/python
runner      = ./bin/figma-run
helpers     = ./helpers.js
profiles    = ./profiles/{ios,material,neutral}.json
profile     = /tmp/claude-figma.profile.json
screenshot  = ./result.png
log tail    = tail -n 30 /tmp/claude-figma.log
fifo        = /tmp/claude-figma.fifo
saved url   = /tmp/claude-figma.url
```

Setup:

```bash
pip install playwright
playwright install firefox
```

Use the provided virtualenv when present. Browser auth is saved in
`.auth-state.json`, which is intentionally ignored because it contains cookies.

---

## First-turn automation — do this immediately, no confirmation

When a Figma URL or Figma-work phrase appears in the user's message:

```bash
python ./run.py --ensure "<FIGMA_URL>"
```

- Idempotent: if the server is already running it prints `server already running` and exits in <1 s. Safe to call every turn.
- If there's no saved session (`.auth-state.json` missing) and no credentials given, `--ensure` opens a Firefox window on the login page and waits up to 5 min for the user to finish manually (Google / SSO / 2FA / password all supported). Tell the user **once**: "browser is open — complete login there, I'll continue as soon as you're in." Then keep polling.
- If the user hasn't given a URL yet, ask once, then proceed.

Do **not** ask "should I start the server?" — the user already said yes by describing Figma work.

---

## Write the script

Before any non-trivial script, **read the full ruleset** at:

```
./scripter.md
```

### Design brief gate

Before creating screens or components, confirm the design direction. If the user
has not supplied an existing design system, profile, or explicit visual brief,
pause after `--ensure` and ask a short brief covering:

- brand/product identity and tone
- colors and theme mode
- font family/weights
- spacing density and corner radius
- required component states

Do not silently default to a generic mobile/iOS style. For quick exploratory work,
propose a concise default brief and wait for the user's acceptance before drawing.
Do not use `--raw` for visual creation just to bypass the profile gate; reserve
`--raw` for probes, smoke tests, and internal diagnostics.

Every non-raw `bin/figma-run` invocation requires
`/tmp/claude-figma.profile.json`. The wrapper prepends `helpers.js` and injects
the resolved profile, so user scripts should not paste helper definitions.

Profile shape:

- `{"preset": "ios" | "material" | "neutral"}` — use a bundled preset.
- `{"preset": "<preset>", "<field>": ...}` — preset plus shallow overrides.
- `{"preset": "custom", "fontFamily": ..., "fontWeights": ..., "colors": ..., "spacing": ..., "radius": ..., "typography": ...}` — full custom profile.

Non-negotiables (from `scripter.md`):

- `(async () => { try { … } catch (e) { figma.notify("❌ " + e.message, { error: true }); console.error(e); } })();`
- `await figma.loadFontAsync({ family, style })` for every font **before** touching any text node.
- `appendChild(frame)` **before** setting `layoutMode`, `resize`, padding, spacing.
- Bind fills/strokes with `figma.variables.setBoundVariableForPaint()` on a cloned paints array (`JSON.parse(JSON.stringify(node.fills))`), **not** `setBoundVariable("fills", …)`.
- Bind numeric props (radius, width, padding) via `setBoundVariable("topLeftRadius", v)`.
- For complex layouts, split creation (Step 1 — hardcoded RGB colours) from variable binding (Step 2 — `findOne` / `findAll` by node name) into two separate scripts.
- Redesign requests must preserve the original frame or section. Create the redesigned/aligned result beside the source, or outside the section when requested, and position it so it does not overlap existing frames.
- If a UI change is ambiguous or requires taste/product judgment not specified by the user, ask before changing it. Do not invent uncertain UI direction silently.
- After every Figma screen creation, redesign, or update, run geometry verification via Scripter or MCP before reporting done. Use two gates when the work contains new or changed UI layout:
  1. **Structural gate:** source-frame preservation when relevant, frame sizes, content-grid alignment, major top-level overlaps, component variant presence, and non-overlap with existing canvas frames.
  2. **Quality gate:** descendant text/text overlaps, probable text overflow, children clipped outside their parent, broken resized component instances, bounded table/content areas, and excessive dead whitespace in generated panels or content zones.
  Treat any layout-audit or layout-quality-audit `BAD` result as not done.
- Center logo/monogram text with Auto Layout center alignment or explicit text alignment; never leave a "Mark Letter" positioned by default at a frame's top-left.
- Name component masters generically or by exact code component name (`Input`, `Button`, `Checkbox`, `VcInput`). Do not prefix component names with the product/client name (`Product/Input`).
- Interactive component masters must include at least Default, Hover, and Active states. If the current turn is intentionally only a static first pass, say that explicitly in the result and list states as the next polishing item.
- Do not use emojis or Unicode glyphs as icons. Use real SVG through the `icon()`
  helper.
- Do not call `figma.closePlugin()` from scripts; the wrapper closes Scripter
  after output capture.

Reference files (read when the pipeline applies):

- `./scripter.md` — full crash-avoidance ruleset.
- `./add-component.md` — component-addition pipeline (Step 1 create → Step 2 bind → Propstar).
- `./figma-comments.md` — Figma REST comments workflow.
- `./pdf-import.md` — PDF → Figma import pipeline (1 slide = 1 frame).

Target script size **< 5 KB**. If bigger, split.

---

## Dispatch

Write the script to a file, then:

```bash
./bin/figma-run /tmp/script.js
```

The wrapper blocks until the script finishes, then prints the captured `print()` output and closes Scripter so the canvas is visible. Typical output:

```
--- output ---
built: Dialer 390x844, 12 keys, 5 tabs
--- result ---
/path/to/result.png
STATUS=ok
```

- **Changelog:** After every code or documentation change (besides editing this file or `changelog.md`), you **MUST** record it in `changelog.md` under the `## [Unreleased]` header.
- The `--- output ---` block is the build script's own `print()` text — that *is* the verification. No separate inspect scripts.
- Exception: screen creation/redesign/update work requires targeted structural and quality layout-audit scripts or MCP geometry reads after the build. Report both verdicts and fix failures before final response.
- `STATUS=ok|timeout|error` is the last line — exit code mirrors it.
- **Fail fast:** on any non-ok status, stop. Report the relevant error line and
  log tail. Do not silently restart, re-run `--ensure`, or resend the script.
- Flags: `--keep-open` (don't close Scripter after — rare, only when chaining scripts that depend on Scripter state), `--restart [URL]` (kill + re-ensure first; URL overrides the saved one).
- `./result.png` — full-page screenshot with Scripter closed. Read it only when you need visual verification.
- `./bin/figma-run-smoketest` — round-trip test that `print()` output reaches stdout. Run after editing `run.py` or the wrapper.

---

## Plugin invocations (Propstar, etc.)

```bash
# Run any Figma plugin; optionally select an action inside it
python ./run.py "__plugin__:Propstar > Create property table"

# After any other plugin, Scripter loses focus — re-open it
sleep 15
python ./run.py "__reopen_scripter__"
```

---

## Common pipelines

- **Add a new component** → `add-component.md` (Step 1 create → verify → Step 2 bind → Propstar).
- **Read / act on Figma comments** → `figma-comments.md` (Figma REST API for fetching; Scripter for edits).
- **Import a PDF presentation** → `pdf-import.md` (one frame per slide, text preserved, images as placeholders).

---

## Code style for generated Scripter JS

- Use clear names (`screen`, `keypadRow`), not minified identifiers.
- Rely on wrapper-provided helpers: `COLOR`, `SPACE`, `RADIUS`, `TYPE`,
  `FONT_FAMILY`, `FONT_WEIGHTS`, `loadFont`, `solid`, `frame`, `row`, `col`,
  `text`, `ICONS`, and `icon`.
- Pass SPACE/RADIUS/TYPE tokens. For intentional raw values, use the helper's
  explicit raw-value escape hatch.
- End screen builds with selection, viewport focus, and one summary print:
  `figma.currentPage.selection = [screen]; figma.viewport.scrollAndZoomIntoView([screen]); print("built: …");`
- Product-specific icon sets may be bundled instead of stored as individual SVG
  files. Do not read private app source paths; extend `helpers.js` from a public
  SVG source such as Lucide.

---

## Known failure modes

- **Keystroke leak:** if Quick Actions fails to open, typed plugin names can hit
  the canvas and activate Figma tools. `run.py` verifies Quick Actions focus and
  uses `click_canvas_safe`, but if a stray 100x100 rectangle appears, inspect
  `/tmp/claude-figma.log` for Quick Actions failures.
- **Scripter paste stacking:** scripts are inserted via Monaco `setValue` to
  avoid Cmd+A/Delete/paste focus bugs. If symptoms return, stop and report
  instead of restarting in a loop.
- **IIFE wrapping:** Scripter may rewrite a trailing expression with an implicit
  return. Always use the async IIFE wrapper and never test with a bare trailing
  `print("…");`.
- **Page selection:** `figma.currentPage` accepts only `PageNode`. Do not set it
  to a frame parent without walking up to the page.
- **Orphans:** `figma.createFrame()` and `figma.createRectangle()` attach to the
  current page by default. Append new nodes to the intended parent immediately
  or clean up by name before rebuilding.
- **SVG import:** `figma.createNodeFromSvg` returns a frame; explicitly resize it.
- **Figma loading:** a browser restart does not wipe file state. If an inspect
  shows an empty page immediately after restart, wait for hydration instead of
  rebuilding.

---

## Session hygiene

- One long-lived Firefox session pinned to one Figma URL. Never kill the browser unless the user asks — disruption = re-login.
- If the Scripter iframe loses focus: `python ./run.py "__reopen_scripter__"`.
- To switch Figma files: `pkill -f "run.py --serve"; rm -f /tmp/claude-figma.fifo`, then `--ensure` with the new URL.

---

## Tool-specific notes

- **Claude Code** — the global skill at `~/.claude/skills/claude-to-figma-scripter/SKILL.md` auto-triggers on Figma URLs; it's a thin shim pointing to this file.
- **Cursor** — add a short `.cursorrules` (or attach this file to context) saying "For Figma work, follow `AGENTS.md` in this project."
- **Aider** — add `AGENTS.md` via `/add AGENTS.md` or reference it in `CONVENTIONS.md`.
- **Gemini / OpenCode / local LLMs** — load `AGENTS.md` as project context.
  Prefer small, direct patches; do not invent unavailable APIs; keep browser and
  Figma automation defensive around nulls, page state, selection, and async
  timing.
- **Any other agent / custom API client** — feed this file (and `scripter.md`) into the model's system prompt or context for any Figma-related task.

Keyboard shortcut handling (Cmd on macOS, Ctrl elsewhere) is managed by `run.py` itself — no agent-side handling needed.
