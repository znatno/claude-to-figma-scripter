# Agent Instructions — claude-to-figma-scripter

Tool-agnostic workflow for any LLM-driven coding assistant (Claude Code, Cursor, Aider, Windsurf, Continue.dev, Copilot agent, custom API clients, etc.) that wants to drive Figma designs via code.

**Trigger whenever** the user mentions a Figma URL (`figma.com/design/…` or `figma.com/file/…`) or any phrasing about creating, modifying, inspecting, or iterating a Figma design — "create a component", "update the token", "add a button to the page", etc.

---

## What this project is

A persistent Playwright/Firefox session logged into Figma with the Scripter plugin open. You write Figma Plugin API JavaScript; the harness pastes it into Scripter and clicks Run; the effect appears on the Figma canvas.

The harness lives at:

```
/Users/ivan/ClaudeProjects/VoicenterProjects/session-logs-update/claude-to-figma-scripter
```

All `run.py` calls below assume the absolute path.

---

## First-turn automation — do this immediately, no confirmation

When a Figma URL or Figma-work phrase appears in the user's message:

```bash
python <PROJECT>/run.py --ensure "<FIGMA_URL>"
```

- Idempotent: if the server is already running it prints `server already running` and exits in <1 s. Safe to call every turn.
- If there's no saved session (`.auth-state.json` missing) and no credentials given, `--ensure` opens a Firefox window on the login page and waits up to 5 min for the user to finish manually (Google / SSO / 2FA / password all supported). Tell the user **once**: "browser is open — complete login there, I'll continue as soon as you're in." Then keep polling.
- If the user hasn't given a URL yet, ask once, then proceed.

Do **not** ask "should I start the server?" — the user already said yes by describing Figma work.

---

## Write the script

Before any non-trivial script, **read the full ruleset** at:

```
<PROJECT>/scripter.md
```

Non-negotiables (from `scripter.md`):

- `async function main() { try { … } catch (e) { figma.notify("❌ " + e.message, { error: true }); console.error(e); } } main();`
- `await figma.loadFontAsync({ family, style })` for every font **before** touching any text node.
- `appendChild(frame)` **before** setting `layoutMode`, `resize`, padding, spacing.
- Bind fills/strokes with `figma.variables.setBoundVariableForPaint()` on a cloned paints array (`JSON.parse(JSON.stringify(node.fills))`), **not** `setBoundVariable("fills", …)`.
- Bind numeric props (radius, width, padding) via `setBoundVariable("topLeftRadius", v)`.
- For complex layouts, split creation (Step 1 — hardcoded RGB colours) from variable binding (Step 2 — `findOne` / `findAll` by node name) into two separate scripts.

Reference files (read when the pipeline applies):

- `<PROJECT>/scripter.md` — full crash-avoidance ruleset.
- `<PROJECT>/add-component.md` — component-addition pipeline (Step 1 create → Step 2 bind → Propstar).
- `<PROJECT>/figma-comments.md` — Figma REST comments workflow.
- `<PROJECT>/pdf-import.md` — PDF → Figma import pipeline (1 slide = 1 frame).

Target script size **< 5 KB**. If bigger, split.

---

## Dispatch

Write the script to a file, then:

```bash
python <PROJECT>/run.py --file /tmp/script.js
```

Outputs:

- `<PROJECT>/output.txt` — captured `print()` / `figma.notify()` text. Read this for data. *(Note: capture is currently flaky on macOS — the server log still reports OK/Error, and `figma.notify()` toasts are still visible on the screenshot.)*
- `<PROJECT>/result.png` — full-page screenshot. Only read it when you need visual verification; don't screenshot by default.
- `/tmp/claude-figma.log` — server log. `tail -n 20 /tmp/claude-figma.log` to confirm the last run printed `OK` or an `Error:`.

After sending a script, wait a few seconds, then check the log / output.

---

## Plugin invocations (Propstar, etc.)

```bash
# Run any Figma plugin; optionally select an action inside it
python <PROJECT>/run.py "__plugin__:Propstar > Create property table"

# After any other plugin, Scripter loses focus — re-open it
sleep 15
python <PROJECT>/run.py "__reopen_scripter__"
```

---

## Common pipelines

- **Add a new component** → `add-component.md` (Step 1 create → verify → Step 2 bind → Propstar).
- **Read / act on Figma comments** → `figma-comments.md` (Figma REST API for fetching; Scripter for edits).
- **Import a PDF presentation** → `pdf-import.md` (one frame per slide, text preserved, images as placeholders).

---

## Session hygiene

- One long-lived Firefox session pinned to one Figma URL. Never kill the browser unless the user asks — disruption = re-login.
- If the Scripter iframe loses focus: `python <PROJECT>/run.py "__reopen_scripter__"`.
- To switch Figma files: `pkill -f "run.py --serve"; rm -f /tmp/claude-figma.fifo`, then `--ensure` with the new URL.

---

## Tool-specific notes

- **Claude Code** — the global skill at `~/.claude/skills/claude-to-figma-scripter/SKILL.md` auto-triggers on Figma URLs; it's a thin shim pointing to this file.
- **Cursor** — add a short `.cursorrules` (or attach this file to context) saying "For Figma work, follow `AGENTS.md` in this project."
- **Aider** — add `AGENTS.md` via `/add AGENTS.md` or reference it in `CONVENTIONS.md`.
- **Any other agent / custom API client** — feed this file (and `scripter.md`) into the model's system prompt or context for any Figma-related task.

Keyboard shortcut handling (Cmd on macOS, Ctrl elsewhere) is managed by `run.py` itself — no agent-side handling needed.
