# Agent Instructions — claude-to-figma-scripter

Tool-agnostic workflow for any LLM-driven coding assistant (Claude Code, Cursor, Aider, Windsurf, Continue.dev, Copilot agent, custom API clients, etc.) that wants to drive Figma designs via code.

**Trigger whenever** the user mentions a Figma URL (`figma.com/design/…` or `figma.com/file/…`) or any phrasing about creating, modifying, inspecting, or iterating a Figma design — "create a component", "update the token", "add a button to the page", etc.

---

## What this project is

A persistent Playwright/Firefox session logged into Figma with the Scripter plugin open. You write Figma Plugin API JavaScript; the harness pastes it into Scripter and clicks Run; the effect appears on the Figma canvas.

The harness lives at the **project root** (the directory containing `run.py`).

All `run.py` calls below use paths relative to the project root (`./`).

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

Non-negotiables (from `scripter.md`):

- `async function main() { try { … } catch (e) { figma.notify("❌ " + e.message, { error: true }); console.error(e); } } main();`
- `await figma.loadFontAsync({ family, style })` for every font **before** touching any text node.
- `appendChild(frame)` **before** setting `layoutMode`, `resize`, padding, spacing.
- Bind fills/strokes with `figma.variables.setBoundVariableForPaint()` on a cloned paints array (`JSON.parse(JSON.stringify(node.fills))`), **not** `setBoundVariable("fills", …)`.
- Bind numeric props (radius, width, padding) via `setBoundVariable("topLeftRadius", v)`.
- For complex layouts, split creation (Step 1 — hardcoded RGB colours) from variable binding (Step 2 — `findOne` / `findAll` by node name) into two separate scripts.

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
- `STATUS=ok|timeout|error` is the last line — exit code mirrors it.
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

## Session hygiene

- One long-lived Firefox session pinned to one Figma URL. Never kill the browser unless the user asks — disruption = re-login.
- If the Scripter iframe loses focus: `python ./run.py "__reopen_scripter__"`.
- To switch Figma files: `pkill -f "run.py --serve"; rm -f /tmp/claude-figma.fifo`, then `--ensure` with the new URL.

---

## Tool-specific notes

- **Claude Code** — the global skill at `~/.claude/skills/claude-to-figma-scripter/SKILL.md` auto-triggers on Figma URLs; it's a thin shim pointing to this file.
- **Cursor** — add a short `.cursorrules` (or attach this file to context) saying "For Figma work, follow `AGENTS.md` in this project."
- **Aider** — add `AGENTS.md` via `/add AGENTS.md` or reference it in `CONVENTIONS.md`.
- **Any other agent / custom API client** — feed this file (and `scripter.md`) into the model's system prompt or context for any Figma-related task.

Keyboard shortcut handling (Cmd on macOS, Ctrl elsewhere) is managed by `run.py` itself — no agent-side handling needed.
