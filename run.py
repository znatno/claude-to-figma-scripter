#!/usr/bin/env python3
"""Execute Figma Plugin API code via the Scripter plugin.

Modes:
    python run.py --serve URL [EMAIL PASSWORD]   # start browser, login, open file, wait for commands
    python run.py --ensure URL [EMAIL PASSWORD]  # idempotent: start server if not running, block until ready
    python run.py "code"                         # send inline code to running server via fifo
    python run.py --file script.js               # send code from a file

Login (in priority order):
  A. `.auth-state.json` exists → skip login entirely.
  B. EMAIL + PASSWORD given → fill the password form and wait for a logged-in URL.
  C. Neither → open the login page and wait up to 5 min for the user to complete login
     manually in the browser (Google / SSO / 2FA / password — all supported).

Server writes `result.png` after each execution and, when Scripter produces output,
`output.txt`. IPC goes through /tmp/claude-figma.fifo; the server mirrors its stdout/stderr
to /tmp/claude-figma.log so --ensure can poll for readiness.
"""

import json
import os
import re
import sys
import time
import asyncio
import subprocess
from pathlib import Path
from playwright.async_api import async_playwright

# Unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DIR = Path(__file__).parent
STATE_PATH = DIR / ".auth-state.json"
SCREENSHOT_PATH = DIR / "result.png"
FIFO_PATH = Path("/tmp/claude-figma.fifo")
LOG_PATH = Path("/tmp/claude-figma.log")
URL_PATH = Path("/tmp/claude-figma.url")  # Last URL passed to --ensure (for restarts).

# Accumulates console messages from the whole page (all frames) between runs.
# scripter_exec clears it before pasting and reads it after running so
# Scripter's print() — which bridges to console.log — ends up in stdout.
CONSOLE_BUFFER: list = []

# Console events we never want to forward as script output. Browser feature-
# policy warnings, Monaco's layout-was-forced notice, Scripter's own timing
# line, etc. — all noise. Matched as substrings.
CONSOLE_NOISE = (
    "Feature Policy:",
    "Layout was forced",
    "Quirks Mode",
    "Clearing and silencing console",
    "JSHandle@",
    "[JavaScript Warning:",
    "[JavaScript Error:",
    "script took ",  # Scripter's "script took Nms" diagnostic
)


def is_console_noise(text: str) -> bool:
    return any(noise in text for noise in CONSOLE_NOISE)

# Modifier key for shortcuts (Cmd on macOS, Ctrl elsewhere). Figma's web UI follows
# the OS convention, and Playwright does not auto-map "Control" → "Meta" on darwin.
MOD = "Meta" if sys.platform == "darwin" else "Control"

# URL pattern meaning "logged in and on a Figma document/dashboard".
LOGGED_IN_URL = re.compile(r"figma\.com/(design|file|files|recent|drafts|community|proto)")


async def _reset_tool(page) -> None:
    """Force the Figma canvas out of any active creation tool.

    Why: letters like R (rectangle), T (text), F (frame), P (pen) are
    Figma canvas shortcuts. If a keystroke leaked to the canvas in a
    prior step (e.g. "Scripter" → "r" activates rectangle tool when
    Quick Actions never opened), the next mouse click drops a 100×100
    primitive at the click location. Pressing Escape + V restores the
    Move tool so clicks and key-combos do not create artifacts.
    """
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(80)
    await page.keyboard.press("v")
    await page.wait_for_timeout(80)


async def click_canvas_safe(page, x: float, y: float) -> None:
    """Click at canvas coordinates only after resetting to the Move tool.

    Use this for any click on the Figma canvas area; never call
    ``page.mouse.click`` directly on canvas coords. See ``_reset_tool``
    for the rationale (keystroke-leak → stray rectangle).
    """
    await _reset_tool(page)
    await page.mouse.click(x, y)


async def open_quick_actions(page, attempts: int = 3) -> bool:
    """Open Figma Quick Actions (Cmd+/) and verify the input is focused.

    Returns True iff an input element became focused on the main page
    (i.e. the Quick Actions search field). If verification fails on
    every attempt, returns False. The caller MUST NOT type afterwards
    when False is returned — typing blind is how we end up with a
    stray 100×100 rectangle on the user's canvas.
    """
    for attempt in range(attempts):
        # Reset tool + clear any open plugin / dialog first.
        await _reset_tool(page)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(120)
        await page.keyboard.press(f"{MOD}+/")
        # Poll briefly for an input/textbox to gain focus. Figma's Quick
        # Actions input is the only element that gets focus from Cmd+/ on
        # the main page, so checking active element tag is sufficient.
        for _ in range(15):  # 15 * 80ms = 1.2s
            await page.wait_for_timeout(80)
            try:
                tag = await page.evaluate(
                    "() => (document.activeElement && document.activeElement.tagName) || ''"
                )
            except Exception:
                tag = ""
            if tag in ("INPUT", "TEXTAREA"):
                return True
        # Didn't open — clean up before retry.
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
        print(f"Quick Actions open attempt {attempt + 1} failed; retrying…",
              file=sys.stderr)
    return False


async def open_plugin(page, plugin_name: str):
    """Open a Figma plugin via Quick Actions.

    Supports 'PluginName > Action' syntax to select a specific action.
    Example: 'Propstar > Create property table'.

    Refuses to type the plugin name if Quick Actions did not open
    (otherwise letters leak to the canvas and can draw a rectangle).
    """
    parts = [p.strip() for p in plugin_name.split(">")]
    name = parts[0]
    action = parts[1] if len(parts) > 1 else None

    if not await open_quick_actions(page):
        print(
            f"Error: Quick Actions never opened; refusing to type '{name}' on canvas",
            file=sys.stderr,
        )
        return

    # Quick Actions is verified focused — safe to type.
    await page.keyboard.type(name, delay=50)
    await page.wait_for_timeout(1000)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(3000)

    if action:
        # Plugin is now open — find and click the action
        for attempt in range(3):
            try:
                item = page.get_by_text(action, exact=False).first
                await item.click()
                await page.wait_for_timeout(5000)
                break
            except Exception:
                await page.wait_for_timeout(1000)
    else:
        await page.wait_for_timeout(3000)

    # Screenshot result
    await page.screenshot(path=str(SCREENSHOT_PATH), scale="css", type="png")


async def reopen_scripter(page):
    """Re-open Scripter plugin after using another plugin.

    Uses the verified ``open_quick_actions`` helper so "Scripter" is
    never typed on the bare canvas (which would toggle S=slice then
    R=rectangle and queue a stray rectangle on the next canvas click).
    """
    for attempt in range(3):
        if not await open_quick_actions(page):
            print(f"Scripter reopen attempt {attempt + 1}: Quick Actions did not open",
                  file=sys.stderr)
            continue

        await page.keyboard.type("Scripter", delay=50)
        await page.wait_for_timeout(800)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

        scripter = page.frame_locator('iframe[title="Plugin: Scripter"]')
        try:
            await scripter.locator("body").wait_for(timeout=5000)
            print("Scripter re-opened.")
            return
        except Exception:
            print(f"Scripter re-open attempt {attempt + 1} failed, retrying...")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(1000)

    print("Warning: could not re-open Scripter", file=sys.stderr)


def scripter_frame(page):
    """Locator for Scripter's inner iframe (4 levels deep)."""
    return (
        page.frame_locator('iframe[title="Plugin: Scripter"]')
        .frame_locator('iframe[name="Network Plugin Iframe"]')
        .frame_locator('iframe[name="Inner Plugin Iframe"]')
        .frame_locator('#iframe0')
    )


async def is_scripter_open(page) -> bool:
    """Is the Scripter iframe currently mounted AND usable?

    A stale outer iframe element can linger briefly after ``figma.closePlugin``,
    so checking count alone returns true when Scripter is actually gone. We
    also probe for the inner Monaco textarea — if that's missing the iframe
    is not in a usable state and the caller must reopen.
    """
    try:
        outer = page.locator('iframe[title="Plugin: Scripter"]')
        if (await outer.count()) == 0:
            return False
        f4 = scripter_frame(page)
        editor = f4.locator('textarea.inputarea').first
        # Short timeout — if the editor isn't there within 1s the plugin
        # is unresponsive (closed or mid-reload).
        await editor.wait_for(state="attached", timeout=1000)
        return True
    except Exception:
        return False


async def ensure_scripter_open(page):
    """If Scripter is closed (e.g. after figma.closePlugin), reopen it."""
    if await is_scripter_open(page):
        return
    print("scripter: reopening (was closed)")
    await reopen_scripter(page)


async def close_scripter(page):
    """Close Scripter so result.png shows a clean canvas.

    ``figma.closePlugin()`` is intercepted by Scripter (it would kill its own
    host), so we click Figma's plugin-window close affordance instead. The
    exact DOM varies with Figma's layout — try a handful of plausible
    selectors and fall back to clicking the top-right of the Scripter iframe
    bounding box (Figma's close button is there).
    """
    if not await is_scripter_open(page):
        return
    # Try a few attribute-based selectors first.
    for selector in (
        '[aria-label="Close" i]',
        '[data-testid*="close" i][class*="plugin" i]',
        'button[title="Close" i]',
    ):
        try:
            loc = page.locator(selector).first
            if (await loc.count()) > 0 and await loc.is_visible():
                await loc.click(timeout=1500)
                await page.wait_for_timeout(400)
                if not await is_scripter_open(page):
                    return
        except Exception:
            continue

    # Fallback: locate the Scripter iframe element and click near its
    # top-right — that's where Figma renders the close "x". Use the
    # canvas-safe wrapper so we never drop a rectangle if some prior
    # step left the canvas in a non-Move tool state.
    try:
        iframe_el = page.locator('iframe[title="Plugin: Scripter"]').first
        box = await iframe_el.bounding_box()
        if box:
            x = box["x"] + box["width"] - 18
            y = box["y"] + 20
            await click_canvas_safe(page, x, y)
            await page.wait_for_timeout(400)
            if not await is_scripter_open(page):
                return
    except Exception:
        pass

    # Last resort: Escape twice often dismisses a focused plugin.
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(200)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)


def _norm_ws(s: str) -> str:
    """Collapse all whitespace and NBSP — used to compare editor DOM vs source."""
    return re.sub(r"\s+", "", (s or "").replace("\u00a0", " "))


async def _monaco_write(textarea, code: str) -> dict:
    """Write *code* via the visible Monaco editor's model.

    Strategy (no guessing):
      1. ``monaco.editor.getEditors()`` returns all instantiated editors.
      2. Pick the one whose container is actually visible — ``offsetParent``
         is non-null AND client rects have non-zero area. Hidden Scripter
         tabs are detached from layout.
      3. If exactly one editor is visible, write to its model.
      4. If zero or more than one is visible, return a diagnostic and let
         the caller fail loudly. No heuristic fallback.

    Returns a dict with ``ok`` plus diagnostic fields.
    """
    return await textarea.evaluate(
        """(el, code) => {
            const win = el.ownerDocument.defaultView;
            const mon = win && win.monaco;
            if (!mon || !mon.editor || typeof mon.editor.getEditors !== 'function') {
                return { ok: false, reason: 'no-monaco-getEditors' };
            }
            const editors = mon.editor.getEditors();
            if (!editors || !editors.length) {
                return { ok: false, reason: 'no-editors' };
            }
            const visible = editors.filter((ed) => {
                try {
                    const node = ed.getDomNode && ed.getDomNode();
                    if (!node) return false;
                    if (!node.offsetParent && node.ownerDocument.body !== node.offsetParent) {
                        // offsetParent is null for display:none/detached subtrees
                        return false;
                    }
                    const r = node.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                } catch (e) { return false; }
            });
            if (visible.length === 0) {
                return { ok: false, reason: 'no-visible-editor',
                         editor_count: editors.length };
            }
            if (visible.length > 1) {
                return { ok: false, reason: 'multiple-visible-editors',
                         visible_count: visible.length,
                         editor_count: editors.length };
            }
            const ed = visible[0];
            const model = ed.getModel && ed.getModel();
            if (!model) {
                return { ok: false, reason: 'visible-editor-no-model' };
            }
            try { model.setValue(code); } catch (e) {
                return { ok: false, reason: 'setValue-throw:' + e.message };
            }
            const got = model.getValue();
            return { ok: got === code,
                     reason: got === code ? 'ok' : 'model-readback-mismatch',
                     got_len: got.length, want_len: code.length,
                     editor_count: editors.length };
        }""",
        code,
    )


async def _verify_visible_matches(f4, code: str) -> dict:
    """Read back the visible Monaco view-lines and confirm they match *code*.

    Monaco only renders visible rows, so for long scripts we compare just
    the first N normalised chars from the head. Scripter scripts in this
    workflow fit on one screen in practice; 120 chars is enough to detect
    a stale tab (different head) without false-positive mismatches on
    trailing-whitespace differences.
    """
    try:
        dom_text = await f4.locator('.monaco-editor .view-lines').first.evaluate(
            """(root) => {
                const lines = Array.from(root.querySelectorAll('.view-line'));
                lines.sort((a, b) => (parseFloat(a.style.top) || 0) - (parseFloat(b.style.top) || 0));
                return lines.map(l => l.innerText).join('\\n');
            }"""
        )
    except Exception as e:
        return {"ok": False, "reason": f"dom-read-error:{e}"}
    want = _norm_ws(code)[:120]
    got = _norm_ws(dom_text)[:120]
    if not want:
        return {"ok": False, "reason": "empty-want"}
    ok = got.startswith(want) or want.startswith(got)
    return {"ok": ok, "reason": "ok" if ok else "visible-mismatch",
            "want_head": want[:60], "got_head": got[:60]}


async def set_editor_code(page, f4, code: str) -> bool:
    """Replace the visible Scripter editor's buffer with *code*.

    Safety contract:
      - Writes ONLY via Monaco's model API on the **visible** editor.
      - Never uses clipboard + Cmd+V (that escapes to the canvas on focus
        loss and creates stray frames/rectangles).
      - On failure, the caller gets a clear False and should NOT proceed
        to run the script.

    Implicit-return caveat:
      Scripter rewrites a trailing bare expression with ``return``; a script
      ending in ``print("…");`` becomes ``returnprint(…)``. Wrap scripts in
      ``(async () => { … })();``. CLAUDE.md documents this rule.

    Returns True iff both the model readback AND the visible-DOM readback
    confirm *code* was installed.
    """
    textarea = f4.locator('textarea.inputarea').first
    try:
        await textarea.wait_for(state="attached", timeout=3000)
    except Exception:
        print("[write] FAIL — Scripter textarea not attached", file=sys.stderr)
        return False

    try:
        result = await _monaco_write(textarea, code)
    except Exception as e:
        result = {"ok": False, "reason": f"evaluate-error:{e}"}

    if not result.get("ok"):
        print(f"[write] FAIL — {result.get('reason')} "
              f"(editors={result.get('editor_count')}, visible={result.get('visible_count')})",
              file=sys.stderr)
        return False

    # Give Monaco a tick to flush the new value into the visible DOM.
    await page.wait_for_timeout(100)

    verify = await _verify_visible_matches(f4, code)
    if not verify.get("ok"):
        print(
            f"[verify] FAIL — {verify.get('reason')} "
            f"want_head={verify.get('want_head')!r} got_head={verify.get('got_head')!r}",
            file=sys.stderr,
        )
        return False

    print(f"[write] ok — {result.get('want_len')} chars → visible Monaco editor "
          f"(of {result.get('editor_count')} total)")
    print(f"[verify] ok — visible DOM matches first {len(verify.get('want_head') or '')} normalised chars")
    return True


async def scrape_scripter_output(page, f4) -> str:
    """Return the text content of Scripter's inline print() widgets.

    Scripter renders each ``print(x)`` call as an inline Monaco content-widget
    above the source line, NOT as a bottom panel. The widget DOM contains the
    stringified value as regular text. We walk the content-widgets container
    and concatenate.
    """
    if not await is_scripter_open(page):
        return ""
    try:
        # Monaco's content widgets are rendered into ``.contentWidgets``.
        # Each Scripter print-result is a child div whose text is the value.
        widgets = f4.locator('.monaco-editor .contentWidgets > div')
        n = await widgets.count()
        lines = []
        for i in range(n):
            try:
                t = (await widgets.nth(i).inner_text()).strip()
            except Exception:
                continue
            if not t:
                continue
            # Filter out editor chrome (suggest widget, hover, find etc.)
            if any(s in t.lower() for s in ("suggest", "parameter hint", "find", "lightbulb")):
                continue
            lines.append(t)
        return "\n".join(lines).strip()
    except Exception:
        return ""


async def wait_for_run_output(page, f4, timeout_s: float = 30.0) -> str:
    """Poll for script output via console buffer + DOM scrape.

    Returns the captured text once it has been stable for ~500ms, or whatever
    we have at ``timeout_s``. Called immediately after Cmd+Enter; the deadline
    must be large enough for heavy build scripts to finish.
    """
    deadline = time.time() + timeout_s
    last_sig = ""
    stable_at: float | None = None

    while time.time() < deadline:
        # Console capture — bridged from Scripter's print() / console.log.
        console_text = "\n".join(CONSOLE_BUFFER).strip()
        # DOM scrape — fallback when console doesn't bubble.
        dom_text = await scrape_scripter_output(page, f4)

        combined = console_text or dom_text
        sig = (len(console_text), len(dom_text), combined)

        if combined:
            if sig == last_sig:
                if stable_at and (time.time() - stable_at) >= 0.5:
                    return combined
            else:
                last_sig = sig
                stable_at = time.time()

        await asyncio.sleep(0.15)

    # Timeout — return best-effort.
    return "\n".join(CONSOLE_BUFFER).strip() or await scrape_scripter_output(page, f4)


async def scripter_exec(page, code: str, timeout_s: float = 30.0, quiet: bool = False) -> str:
    """Paste and run code in Scripter, capture print() output, emit STATUS.

    Returns the captured output text. Output contract (read by
    ``bin/figma-run``):
        STATUS=ok|timeout|error
        --- output ---
        <captured text>
        --- end output ---
        OK → /path/to/result.png

    ``quiet=True`` suppresses the STATUS/output block (used by the internal
    hydration probe so startup logs stay clean).
    """
    f4 = scripter_frame(page)

    # 1. Scripter may have been closed by figma.closePlugin() in the previous
    #    script. Reopen transparently so the agent doesn't have to care.
    await ensure_scripter_open(page)

    # 2. Clear console buffer so this run starts clean.
    CONSOLE_BUFFER.clear()

    # 3. Dismiss leftover popups (autocomplete from the previous run).
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(150)

    # 4. Replace the editor buffer atomically via Monaco's setValue API on
    #    the visible editor. Fail-fast policy: ONE attempt. If the write
    #    fails we HARD-FAIL rather than retry — retries cascade into many
    #    Scripter popups for the user. bin/figma-run's exit signals Claude
    #    to stop and wait for direction.
    replaced = await set_editor_code(page, f4, code)
    if not replaced:
        msg = ("editor write failed on first attempt; refusing to retry "
               "(would trigger Scripter popups and risk canvas paste)")
        print(f"[run] ABORT — {msg}", file=sys.stderr)
        if not quiet:
            print("STATUS=error")
            print("--- output ---")
            print(f"(aborted: {msg})")
            print("--- end output ---")
        return ""

    # 5. Focus the editor's inputarea so Cmd+Enter targets Monaco. Then
    #    verify focus actually landed on the textarea inside the Scripter
    #    iframe — if it didn't, pressing Cmd+Enter could hit the Figma
    #    canvas instead (and any stray keystrokes could move the page).
    try:
        await f4.locator('textarea.inputarea').first.focus(timeout=2000)
    except Exception:
        try:
            await f4.locator('.monaco-editor .view-lines').first.click(timeout=2000)
        except Exception:
            pass
    await page.wait_for_timeout(120)

    focus_ok = False
    try:
        focus_info = await f4.locator('textarea.inputarea').first.evaluate(
            """(el) => {
                const active = el.ownerDocument.activeElement;
                return {
                    is_textarea: active === el,
                    active_tag: active ? active.tagName : null,
                    active_cls: active && active.className ? String(active.className).slice(0, 80) : null,
                };
            }"""
        )
        focus_ok = bool(focus_info.get("is_textarea"))
    except Exception as e:
        focus_info = {"error": str(e)}
    if not focus_ok:
        msg = f"focus not on Scripter textarea (active={focus_info}); refusing to press Cmd+Enter"
        print(f"[focus] FAIL — {msg}", file=sys.stderr)
        print(f"[run] ABORT — {msg}", file=sys.stderr)
        if not quiet:
            print("STATUS=error")
            print("--- output ---")
            print(f"(aborted: {msg})")
            print("--- end output ---")
        return ""
    print("[focus] ok — textarea.inputarea inside Scripter iframe has focus")

    # 6. Run. Cmd+Enter — we just verified focus is on the Scripter textarea,
    #    so this keystroke cannot leak to the Figma canvas.
    await page.keyboard.press(f"{MOD}+Enter")
    print("[run] Cmd+Enter dispatched")

    # 7. Poll adaptively for output. Returns quickly for simple scripts,
    #    waits up to ``timeout_s`` for heavy builds.
    output = await wait_for_run_output(page, f4, timeout_s=timeout_s)

    status = "ok" if output else "timeout"
    source = "console" if "\n".join(CONSOLE_BUFFER).strip() else ("dom" if output else "none")
    print(f"[output] source={source}, status={status}, len={len(output)}")

    # 8. Persist output.txt for compatibility; emit to stdout for the wrapper.
    if output:
        (DIR / "output.txt").write_text(output)
    if not quiet:
        print(f"STATUS={status}")
        print("--- output ---")
        print(output or f"(no print() output captured within {timeout_s:.0f}s)")
        print("--- end output ---")

    # 9. Screenshot after script finishes. If the script called
    #    figma.closePlugin() (directly or via setTimeout), wait a beat so
    #    the plugin UI is actually gone before the shot.
    await page.wait_for_timeout(500)
    try:
        await page.screenshot(path=str(SCREENSHOT_PATH), scale="css", type="png")
    except Exception as e:
        print(f"screenshot failed: {e}", file=sys.stderr)

    return output


async def serve(url: str, email: str = None, password: str = None):
    """Long-running server: open Figma, listen for code on fifo."""
    # Create fifo
    if FIFO_PATH.exists():
        FIFO_PATH.unlink()
    os.mkfifo(FIFO_PATH)

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=False)
        if STATE_PATH.exists():
            ctx = await browser.new_context(storage_state=str(STATE_PATH))
        else:
            ctx = await browser.new_context()

        page = await ctx.new_page()

        # Capture console events from all frames into CONSOLE_BUFFER so
        # scripter_exec can read print() output. Scripter's ``print`` bridges
        # to ``console.log`` inside the plugin iframe; Playwright's page-level
        # listener bubbles those up regardless of iframe nesting.
        def _on_console(msg):
            try:
                text = msg.text
            except Exception:
                return
            if text and not is_console_noise(text):
                CONSOLE_BUFFER.append(text)
        page.on("console", _on_console)

        # --- Login ------------------------------------------------------
        if not STATE_PATH.exists():
            if email and password:
                # Case B — auto-fill password form.
                await page.goto("https://www.figma.com/login")
                await page.wait_for_timeout(3000)
                await page.get_by_role("textbox", name="Email").fill(email)
                await page.get_by_role("textbox", name="Password").fill(password)
                await page.get_by_role("button", name="Log in").click()
                try:
                    await page.wait_for_url(LOGGED_IN_URL, timeout=120_000)
                except Exception:
                    print(
                        "Warning: did not detect a logged-in URL within 2 min; "
                        "saving storage state anyway.",
                        file=sys.stderr,
                    )
            else:
                # Case C — manual login (Google / SSO / 2FA / password all supported).
                await page.goto("https://www.figma.com/login")
                print(
                    "▶ Please complete login manually in the browser "
                    "(Google / SSO / 2FA all fine). Waiting up to 5 minutes…",
                    file=sys.stderr,
                )
                await page.wait_for_url(LOGGED_IN_URL, timeout=300_000)
            await ctx.storage_state(path=str(STATE_PATH))
            print("Logged in, session saved.")

        await page.goto(url)
        await page.wait_for_timeout(5000)

        # --- Open Scripter ---------------------------------------------
        # Each attempt verifies Quick Actions opened (via focus on the
        # input) BEFORE typing "Scripter". Typing blind on the canvas
        # would activate Figma's R = rectangle tool and leave a
        # stray 100×100 rectangle on the file.
        for attempt in range(3):
            if not await open_quick_actions(page):
                print(f"Scripter open attempt {attempt + 1}: Quick Actions did not open",
                      file=sys.stderr)
                continue
            await page.keyboard.type("Scripter", delay=50)
            await page.wait_for_timeout(800)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(3000)

            scripter = page.frame_locator('iframe[title="Plugin: Scripter"]')
            try:
                await scripter.locator("body").wait_for(timeout=5000)
                print("Scripter opened.")
                break
            except Exception:
                print(f"Scripter not found (attempt {attempt + 1}), retrying...")
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(1000)
        else:
            print("Error: could not open Scripter after 3 attempts", file=sys.stderr)
            await browser.close()
            return

        # --- Hydration wait --------------------------------------------
        # Scripter being mounted does NOT mean Figma has finished loading the
        # file. After a fresh browser start the canvas may still be hydrating,
        # which makes ``figma.currentPage.children`` briefly empty and
        # previously looked like file corruption. Probe via a tiny Scripter
        # script that prints the child count; retry until it responds.
        # Must be IIFE-wrapped: Scripter's implicit-return transform breaks
        # bare top-level statements installed via setValue (produces
        # ``'returnprint' is not defined``). See ``set_editor_code`` docstring.
        probe = "(async () => { print('HYDRATED:' + figma.currentPage.children.length); })();"
        hydrated = False
        for attempt in range(6):
            try:
                text = await scripter_exec(page, probe, timeout_s=5.0, quiet=True)
            except Exception as e:
                print(f"hydration probe error (attempt {attempt + 1}): {e}")
                await page.wait_for_timeout(2000)
                continue
            if text and "HYDRATED:" in text:
                print(f"hydration ok — {text.strip().splitlines()[-1]}")
                hydrated = True
                break
            print(f"hydration probe empty (attempt {attempt + 1}); retrying…")
            await page.wait_for_timeout(2000)
        if not hydrated:
            print(
                "warning: hydration probe never responded; proceeding anyway",
                file=sys.stderr,
            )

        # --- URL node/page enforcement ---------------------------------
        # Figma's stored session state can override the URL's requested
        # page — users pass a URL with ``node-id=519-12368`` expecting the
        # viewport to land on that node, then see a different page instead.
        # Parse node-id out of the URL and force the active page + viewport
        # to match.
        m = re.search(r'node-id=([0-9A-Za-z_:-]+)', url)
        if m:
            node_id = m.group(1).replace('-', ':', 1)
            nav_script = (
                "(async () => {\n"
                "  try {\n"
                "    await figma.loadAllPagesAsync();\n"
                f"    const n = await figma.getNodeByIdAsync({json.dumps(node_id)});\n"
                "    if (!n) { print('NAV_NO_NODE'); return; }\n"
                "    let p = n; while (p && p.type !== 'PAGE') p = p.parent;\n"
                "    if (p && figma.currentPage !== p) { figma.currentPage = p; }\n"
                "    figma.viewport.scrollAndZoomIntoView([n]);\n"
                "    print('NAVIGATED:' + (p ? p.name : '?'));\n"
                "  } catch (e) { print('NAV_ERR:' + e.message); }\n"
                "})();"
            )
            try:
                text = await scripter_exec(page, nav_script, timeout_s=10.0, quiet=True)
                if text:
                    last = text.strip().splitlines()[-1]
                    print(f"url-node nav: {last}")
            except Exception as e:
                print(f"url-node nav failed: {e}", file=sys.stderr)

        print(f"Ready. Send code to {FIFO_PATH}")
        print(f"  echo 'figma code' > {FIFO_PATH}")

        # --- Command loop ----------------------------------------------
        while True:
            with open(FIFO_PATH, 'r') as fifo:
                code = fifo.read().strip()
            if not code:
                continue
            if code == "__quit__":
                break
            if code.startswith("__plugin__:"):
                plugin_name = code.split(":", 1)[1].strip()
                try:
                    await open_plugin(page, plugin_name)
                    print(f"Plugin '{plugin_name}' done → {SCREENSHOT_PATH}")
                except Exception as e:
                    print(f"Plugin error: {e}", file=sys.stderr)
                continue
            if code == "__reopen_scripter__":
                try:
                    await reopen_scripter(page)
                except Exception as e:
                    print(f"Reopen error: {e}", file=sys.stderr)
                continue
            if code == "__close_scripter__":
                try:
                    await close_scripter(page)
                    # Move mouse far off-canvas so the "Close" tooltip from the
                    # hover doesn't end up in the screenshot.
                    await page.mouse.move(5, 5)
                    await page.wait_for_timeout(400)
                    await page.screenshot(path=str(SCREENSHOT_PATH), scale="css", type="png")
                except Exception as e:
                    print(f"Close error: {e}", file=sys.stderr)
                continue
            try:
                await scripter_exec(page, code)
                print(f"OK → {SCREENSHOT_PATH}")
            except Exception as e:
                print(f"STATUS=error")
                print(f"Error: {e}", file=sys.stderr)

        await browser.close()
    FIFO_PATH.unlink(missing_ok=True)


def send_code(code: str):
    """Send code to running server via fifo."""
    if not FIFO_PATH.exists():
        print(
            "Error: server not running. Start with:\n"
            "  python run.py --ensure URL [EMAIL] [PASSWORD]",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(FIFO_PATH, 'w') as f:
        f.write(code)
    print(f"Sent. Check {SCREENSHOT_PATH}")


def ensure_server(url: str, email: str = None, password: str = None) -> int:
    """Spawn `--serve` in the background if the fifo is absent, then block until Scripter is open.

    Idempotent: if the fifo already exists, returns immediately.
    Returns 0 on success, non-zero on timeout/failure.
    """
    if FIFO_PATH.exists():
        print("server already running")
        return 0

    manual_login = not STATE_PATH.exists() and not (email and password)
    if manual_login:
        print(
            "▶ No saved session — a Firefox window will open; complete login manually there "
            "(Google / SSO / 2FA / password all fine). I'll keep polling…",
            file=sys.stderr,
        )

    # Reset log so readiness polling sees only fresh output.
    LOG_PATH.write_text("")
    # Persist the URL so `bin/figma-run --restart` can re-launch without args.
    URL_PATH.write_text(url)

    cmd = [sys.executable, "-u", str(Path(__file__).resolve()), "--serve", url]
    if email:
        cmd.append(email)
    if password:
        cmd.append(password)

    log_fh = open(LOG_PATH, "w")
    subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    log_fh.close()

    # Case C (manual login) may need up to 5 min — budget generously.
    # Auto-login path needs room for Scripter open (≤30s) + hydration probe
    # retries (≤60s) on a slow file load.
    timeout = 360 if manual_login else 180
    deadline = time.time() + timeout

    print(
        f"starting server (budget {timeout}s); tail log with: tail -f {LOG_PATH}",
        file=sys.stderr,
    )

    while time.time() < deadline:
        text = LOG_PATH.read_text() if LOG_PATH.exists() else ""
        # "Ready." is only printed after Scripter opens AND the hydration
        # probe confirms Figma's file has loaded (children populated or
        # confirmed empty). Waiting on "Scripter opened." alone was
        # reporting ready before Figma finished loading the file.
        if "Ready. Send code" in text:
            print("server ready")
            return 0
        if "could not open Scripter" in text:
            print("server failed to open Scripter", file=sys.stderr)
            print(text[-2000:], file=sys.stderr)
            return 1
        time.sleep(1)

    print(f"timeout after {timeout}s waiting for server to be ready", file=sys.stderr)
    tail = (LOG_PATH.read_text() if LOG_PATH.exists() else "")[-2000:]
    print(tail, file=sys.stderr)
    return 1


def main():
    if "--serve" in sys.argv:
        idx = sys.argv.index("--serve")
        url = sys.argv[idx + 1]
        email = sys.argv[idx + 2] if len(sys.argv) > idx + 2 else None
        password = sys.argv[idx + 3] if len(sys.argv) > idx + 3 else None
        asyncio.run(serve(url, email, password))
    elif "--ensure" in sys.argv:
        idx = sys.argv.index("--ensure")
        url = sys.argv[idx + 1]
        email = sys.argv[idx + 2] if len(sys.argv) > idx + 2 else None
        password = sys.argv[idx + 3] if len(sys.argv) > idx + 3 else None
        sys.exit(ensure_server(url, email, password))
    elif "--file" in sys.argv:
        idx = sys.argv.index("--file")
        with open(sys.argv[idx + 1]) as f:
            send_code(f.read().strip())
    elif len(sys.argv) > 1:
        send_code(sys.argv[1])
    else:
        print("Usage:")
        print("  python run.py --serve URL [EMAIL] [PASSWORD]   # start server (creds optional)")
        print("  python run.py --ensure URL [EMAIL] [PASSWORD]  # start if not running, block until ready")
        print('  python run.py "code"                           # send inline code')
        print("  python run.py --file script.js                 # send code from file")


if __name__ == "__main__":
    main()
