# claude-to-figma-scripter

**To build UI:** confirm `/tmp/claude-figma.profile.json` is set (see [Design profile](#design-profile)), write the body JS to `/tmp/<name>.js`, run `./bin/figma-run /tmp/<name>.js`, read `result.png`. The wrapper prepends `helpers.js` + the resolved profile — **do not paste the helper library into the body**.

For component-set / variable-binding pipelines (Step 1 / Step 2 / Propstar) read `scripter.md` and `add-component.md`. For one-shot screens, `helpers.js` + the skill's API surface is everything you need.

## Environment

```
python      = ./.venv/bin/python
runner      = ./bin/figma-run            # wraps run.py, auto-prepends helpers
helpers     = ./helpers.js               # single source of truth for COLOR/SPACE/...
profiles    = ./profiles/{ios,material,neutral}.json
profile     = /tmp/claude-figma.profile.json   # user's chosen tokens (required)
screenshot  = ./result.png               # overwritten on every run
log tail    = tail -n 30 /tmp/claude-figma.log
fifo        = /tmp/claude-figma.fifo     # exists ⇔ server is up
saved url   = /tmp/claude-figma.url      # written by --ensure, read by --restart
```

First time per session, start the server (idempotent — instant if already running):

```
python run.py --ensure '<FIGMA_URL>'
```

## Design profile

Every build run requires `/tmp/claude-figma.profile.json`. If it's missing, `bin/figma-run` refuses to run — this is intentional: Claude must ask the user for font / colors / spacing / radius / typography via `AskUserQuestion` before generating a script, instead of silently defaulting to iOS.

Profile shape — one of:

- `{"preset": "ios" | "material" | "neutral"}` — load a preset from `profiles/` verbatim.
- `{"preset": "<preset>", "<field>": ...}` — preset + shallow overrides (e.g. override `fontFamily`).
- `{"preset": "custom", "fontFamily": …, "fontWeights": …, "colors": …, "spacing": …, "radius": …, "typography": …}` — full custom.

The wrapper bakes the resolved object into `const PROFILE = {...};` at the top of the buffer; `helpers.js` derives `COLOR`, `SPACE`, `RADIUS`, `TYPE`, `FONT_FAMILY`, `FONT_WEIGHTS` from it. Reuse the profile for every script in the session — only re-ask if the user changes it.

## Project map

- `run.py` — Playwright server: launches Firefox, opens Figma + Scripter, listens on the fifo. Captures `print()` output via console bridge + DOM scrape. Waits for Figma hydration before reporting ready.
- `bin/figma-run` — pinned-python wrapper. Default: send file, print captured output, close Scripter. Flags: `--restart [URL]` (kill + re-ensure), `--keep-open` (don't close Scripter after). Auto-retries once on timeout.
- `bin/figma-run-smoketest` — round-trip test that a `print()` line reaches stdout. Run after editing `run.py` or the wrapper.
- `scripter.md` — deep ruleset (read before any non-trivial script).
- `add-component.md`, `figma-comments.md`, `pdf-import.md` — pipeline-specific guides.
- `result.png` — last screenshot. Source of truth for visual verification.
- Skill: `~/.claude/skills/claude-to-figma-scripter/SKILL.md` — helper library + design defaults.

## Known issues

- **Keystroke leak → 100×100 grey rectangle.** If Figma's Quick Actions doesn't open on `Cmd+/`, subsequent `type("Scripter")` keystrokes land on the canvas, where `S` activates slice and `R` activates rectangle. A later mouse click then drops a 100×100 rectangle at the click location. `run.py` now verifies Quick Actions focus (via `open_quick_actions`) before typing and uses `click_canvas_safe` (Escape + V → Move tool → click) for any canvas-area click. `helpers.js` also sweeps any stray 100×100 `Rectangle N` nodes at the top of every build script as defense-in-depth. If you still see one appear, inspect `/tmp/claude-figma.log` — the Quick-Actions verification prints `Quick Actions open attempt N failed` when it trips.
- **Scripter paste stacking** — fixed in `run.py` via `set_editor_code`, which replaces the buffer atomically through Monaco's `setValue` API instead of keyboard Cmd+A+Delete+paste. The old approach was unreliable because focus often landed on an inline `print()` content widget, Cmd+A silently no-op'd, and paste concatenated onto the prior buffer — causing duplicate `const` SyntaxErrors that produced stack-trace-only output (no print output) and orphan nodes from the partial prior run. Scripter also has multiple models (one per open tab); the helper picks the active one by matching the rendered `.view-lines` text. If you still see symptoms like that, stop and ask the user — do not `--restart`.
- **IIFE wrapping is mandatory.** Scripter rewrites the last expression with an implicit `return` so scripts can end in a bare expression. When we paste via `setValue`, that transform mis-handles scripts that end in a bare `print("…");` and fails with ``'returnprint' is not defined``. Wrapping every script in `(async () => { … })();` makes the transform skip the implicit return entirely. The helper library template and `bin/figma-run-smoketest` already follow this — never paste a bare `print("…");` as a test.
- **`figma.currentPage` only accepts a `PageNode`.** A top-level frame's `.parent` is often a `SectionNode`, not a page — setting `figma.currentPage = frame.parent` throws `figma.currentPage expects a PageNode`. Walk up first: `let p = node; while (p && p.type !== 'PAGE') p = p.parent;`. Better: don't set `figma.currentPage` at all — the server navigates to the node in the URL after hydration, and scripts should stay on that page. Only set it when you genuinely need to move work to another page, and restore it on exit.
- **`figma.createFrame()` / `createRectangle()` attach to `figma.currentPage`** by default. If a script errors before appending them to a proper parent, they become orphans on the page. Prefer patterns that create the frame and immediately append to a known parent, or cleanup by name at the top of the script: `figma.currentPage.children.filter(c => c.name === 'my-thing').forEach(c => c.remove());`.
- **Emoji-in-Inter renders weird glyphs** — Unicode symbols like ☎ ★ ✓ render as Inter's fallback, not as icons. **Never use emojis or Unicode glyphs as icons.** Use `icon("name")` from the helper library (which now throws on unknown names instead of rendering a placeholder).
- **`figma.createNodeFromSvg` returns a FRAME** that ignores SVG `width`/`height` — always call `.resize(w, h)` on it.
- **Browser restarts never wipe Figma file state.** Figma autosaves continuously. If an inspect right after `--restart` shows an empty page, the file hasn't finished loading — wait a few seconds and re-inspect. Do not rebuild. The server's `--ensure` path waits for a hydration probe (see `output.txt` / log `hydration ok — HYDRATED:N`) before signaling ready.
- **URL page enforcement.** `--ensure` parses `node-id=…` out of the URL and runs a post-hydration probe that sets `figma.currentPage` to the node's parent page and scrolls it into view. Without this Figma's stored session state could override the URL's page silently.

## Icon sourcing policy

1. **Primary:** the `ICONS` SVG map in `./helpers.js` (sourced from Lucide). Use via `icon("phone")`, `icon("mic")`, etc.
2. **Missing icon:** add the SVG markup as a new entry to `ICONS` in `helpers.js`. Source from <https://lucide.dev>. Record the addition in `changelog.md`.
3. **Product-specific icon sets** may be bundled rather than stored as individual SVG files. Do not read private app source paths; extend helpers.js from a public SVG source instead.
4. **Hard no:** emojis, Unicode glyphs (☎ ★ ✓), `figma.createText` for icon characters. Always real SVG.
5. `icon()` now throws on unknown names (no silent placeholder). Missing icons fail the script loudly.

## Verification & Changelog policy

- `result.png` is the source of truth. Read it once. Don't write `dump.js` / `check.js` / `getid.js` scripts.
- If you need structural info (node ids, dimensions, child count), append `print(summary)` to the build script — the wrapper prints it between `--- output ---` / `--- end output ---`. No second script.
- The build script must end with one summary line, e.g. `print("built: Dialer 390x844, 12 keys, 5 tabs");` — that *is* the verification.
- The wrapper closes Scripter after a successful run so `result.png` shows a clean canvas. Pass `--keep-open` if you want Scripter to stay (rare — only when chaining multiple scripts that depend on Scripter state).
- To confirm capture is working end-to-end, run `bin/figma-run-smoketest` — it prints a timestamped marker and asserts it round-trips through stdout (uses `--raw` so no profile is required).
- **Changelog:** After every code or documentation change (besides editing this file or `changelog.md`), you **MUST** record it in `changelog.md` under the `## [Unreleased]` header.

## Failure policy (fail-fast)

- `bin/figma-run` runs ONCE per invocation. No auto-restart on timeout, no inner retry in `scripter_exec`. On any non-ok status the wrapper prints the last 30 lines of `/tmp/claude-figma.log` and exits non-zero.
- **Claude must stop on non-ok.** Paste the relevant error line + log tail for the user, explain what likely failed, and wait for direction. Do NOT re-invoke `--restart`, re-run `--ensure`, or re-send the script. Each silent retry triggers another wave of Scripter popups and wastes the user's time.
- Running scripts without a profile (`/tmp/claude-figma.profile.json` missing) is also a non-ok — the wrapper prints what to do and exits 2.

## Code style for generated Scripter JS

- No minified or single-letter identifiers outside loop counters. `screen`, `keypadRow` — not `S`, `KR`.
- **Do NOT paste the helper library into scripts.** The wrapper prepends `helpers.js` + resolved profile automatically. Scripts assume `COLOR`, `SPACE`, `RADIUS`, `TYPE`, `FONT_FAMILY`, `FONT_WEIGHTS`, `loadFont`, `solid`, `frame`, `row`, `col`, `text`, `ICONS`, `icon` are in scope.
- Pass SPACE/RADIUS/TYPE tokens, never raw pixel literals. The helper throws on raw numbers for `pad`/`gap` — use `SPACE.<key>` or `{raw: N}` for explicit opt-out.
- Wrap the body in `(async () => { try { … } catch (e) { figma.notify("Script failed: " + e.message, {error:true}); console.error(e); } })();`
- End with `figma.currentPage.selection = [screen]; figma.viewport.scrollAndZoomIntoView([screen]); print("built: …");`
- **Do NOT** call `figma.closePlugin()` yourself — the wrapper closes Scripter after each run so the canvas is visible in `result.png`. Calling it yourself races output capture and may hide the `print("built: …")` summary.
- Output JS only when a tool is going to paste it — no markdown fences, no commentary.

## Figma comments

REST API — see `figma-comments.md`. Needs a token; if absent, ask the user for one from <https://www.figma.com/developers/api#access-tokens>.
