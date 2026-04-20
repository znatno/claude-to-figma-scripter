# claude-to-figma-scripter

AI-driven Figma design automation. Claude Code writes Figma Plugin API scripts, a persistent Playwright/Firefox session pastes them into the Scripter plugin, and the result appears on the Figma canvas.

## How it works

```
Claude Code  →  run.py (Playwright/Firefox)  →  Figma Scripter  →  Figma canvas
```

1. `run.py` launches Firefox, signs into Figma, and opens the Scripter plugin.
2. Claude Code sends Plugin API scripts through a named pipe (`/tmp/claude-figma.fifo`).
3. Scripter runs the code inside Figma — creating frames, components, text, Auto Layout.
4. Canvas state is read back via `output.txt` dumps from `print()` / `figma.notify()` (no screenshots by default).

## Requirements

- Python 3.10+
- Playwright (`pip install playwright && playwright install firefox`)
- A Figma account with the [Scripter plugin](https://www.figma.com/community/plugin/757836922707087381) installed.

Keyboard shortcuts are OS-aware out of the box: Cmd on macOS, Ctrl on Linux/Windows.

## Setup

### macOS

No display or sandbox fiddling needed. Firefox runs natively with a visible window.

```bash
pip install playwright
playwright install firefox
```

Then jump to **Starting the server** below — `python run.py --ensure URL` just works.

### Linux

Playwright's Firefox needs a display. Either run on a workstation (X/Wayland already available) or use Xvfb on a headless server.

```bash
# Playwright
pip install playwright
playwright install firefox
playwright install-deps    # grabs system libs (libgtk, etc.)

# If AppArmor blocks unprivileged user namespaces (Ubuntu 23+):
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0

# Headless display (only if no X server)
sudo apt install xvfb
Xvfb :99 -screen 0 1920x1080x24 &
```

Prepend `DISPLAY=:99` to the `run.py` command when using Xvfb.

### Windows

Not actively tested. In theory works the same as macOS/Linux (Playwright supports Windows). Run PowerShell / cmd with the same `pip install playwright && playwright install firefox` incantation. `run.py` treats Windows like Linux for keyboard shortcuts (Ctrl).

## Starting the server

Idempotent — safe to call on every turn. If the fifo exists, it exits in under a second.

```bash
# No credentials: opens the login page and waits up to 5 min for you to finish manually
python run.py --ensure "FIGMA_FILE_URL"

# With credentials: fills the email/password form automatically
python run.py --ensure "FIGMA_FILE_URL" EMAIL PASSWORD

# Manual foreground start (blocks the terminal until shutdown)
python run.py --serve "FIGMA_FILE_URL"
```

On Linux with Xvfb prefix: `DISPLAY=:99 python run.py --ensure "FIGMA_FILE_URL"`.

### Login modes

Priority order:

1. **`.auth-state.json` exists** → session is restored, no login step.
2. **Credentials passed on CLI** → email/password form is auto-filled; we wait up to 2 min for the post-login redirect.
3. **No credentials** → the login page opens and the server waits up to 5 min for you to finish in the browser. Google, SSO, 2FA, or plain password all work. Session is saved after any successful login.

## Running scripts

```bash
# Inline
python run.py "figma.createRectangle()"

# From a file (recommended for anything non-trivial)
python run.py --file script.js
```

After each run:

- `output.txt` — captured `print()` / `figma.notify()` text.
- `result.png` — full-page screenshot (only consult when visual verification is needed).
- `/tmp/claude-figma.log` — server log; `tail` for `OK` or `Error:`.

## Plugins and Propstar

```bash
# Invoke any Figma plugin (optionally select an action within it)
python run.py "__plugin__:Propstar > Create property table"

# Other plugins steal focus from Scripter — re-open it
python run.py "__reopen_scripter__"
```

## Project structure

```
run.py              — Playwright server: browser automation + fifo listener
scripter.md         — Code-generation rules for Figma Scripter
add-component.md    — Universal pipeline for adding components from code to Figma
pdf-import.md       — Pipeline for importing PDF presentations into Figma
figma-comments.md   — Figma REST API comments → Scripter edits
CLAUDE.md           — Session instructions for Claude Code
plugin/             — Custom Figma plugin (alternative to Scripter)
  code.js           — Plugin backend (eval + print capture)
  ui.html           — Plugin UI (code editor + output)
  manifest.json     — Plugin manifest
```

## Key concepts

- **Two-step builds.** Create the visual structure first (Step 1, hardcoded RGB colours), bind Figma variables second (Step 2, `findOne`/`findAll` by node name). Mixing them in one script triggers silent failures.
- **No screenshots by default.** Verify canvas state through `print()` dumps — cheaper, more reliable, token-efficient.
- **Atomic components.** Complex components are assembled from instances of atomic components. Style bindings live on the atoms; instances inherit automatically.
- **Figma Variables.** All colours, radii, sizes bind to Figma Variables via `setBoundVariableForPaint()` (fills/strokes) and `setBoundVariable()` (numerics).
- **Text Styles.** All text uses local Figma Text Styles (`body/sm/medium`, `heading/h1/bold`, etc.).
- **Propstar.** After creating a Component Set, run Propstar to lay variants out in a grid.
- **Clipboard paste.** Scripts are injected via `navigator.clipboard.writeText` + the OS paste shortcut (Cmd+V on macOS, Ctrl+V elsewhere).

## Scripter rules

See [`scripter.md`](scripter.md) for the full ruleset that prevents runtime crashes:

- Load fonts before any text operation.
- `appendChild()` before `resize()` or layout properties.
- Set `layoutMode` before any Auto Layout props.
- Colours in RGB 0–1, not hex.
- `findOne()` for text overrides in instances.

## Figma comments workflow

See [`figma-comments.md`](figma-comments.md) — read comments via REST API and apply fixes through Scripter:

```
Fetch unresolved comments → Parse → Apply via Scripter → Verify
```

Requires a **Figma Personal Access Token** (create one at <https://www.figma.com/developers/api#access-tokens>).

## PDF import

See [`pdf-import.md`](pdf-import.md):

```
Read PDF → Analyse slides → 1 script per slide → Verify
```

Text is preserved in full; images and charts become placeholder rectangles. Each slide becomes a 1920×1080 frame.

## Component-addition pipeline

See [`add-component.md`](add-component.md):

```
Read source code → Step 1 (create) → Verify sizes →
Step 2 (bind variables) → Verify bindings → Propstar
```

Includes colour/radius/text-style mappings, helpers (`bF()`, `bS()`, `bN()`, `bT()`, `bR()`, `bE()`), and a common-mistakes table.

## License

MIT
