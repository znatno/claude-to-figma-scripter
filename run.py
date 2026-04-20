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

# URL pattern meaning "logged in and on a Figma document/dashboard".
LOGGED_IN_URL = re.compile(r"figma\.com/(design|file|files|recent|drafts|community|proto)")


async def open_plugin(page, plugin_name: str):
    """Open a Figma plugin via Quick Actions.

    Supports 'PluginName > Action' syntax to select a specific action.
    Example: 'Propstar > Create property table'
    """
    parts = [p.strip() for p in plugin_name.split(">")]
    name = parts[0]
    action = parts[1] if len(parts) > 1 else None

    # Close any open plugin/dialog
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)

    # Click on canvas to ensure focus
    await page.mouse.click(100, 300)
    await page.wait_for_timeout(500)

    # Open Quick Actions
    await page.keyboard.press("Control+/")
    await page.wait_for_timeout(1500)

    # Type plugin name
    await page.keyboard.type(name, delay=50)
    await page.wait_for_timeout(1500)

    # Press Enter to open the plugin first
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
    """Re-open Scripter plugin after using another plugin."""
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)
    await page.mouse.click(100, 300)
    await page.wait_for_timeout(500)

    for attempt in range(3):
        await page.keyboard.press("Control+/")
        await page.wait_for_timeout(1000)
        await page.keyboard.type("Scripter", delay=50)
        await page.wait_for_timeout(1000)
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

    print("Warning: could not re-open Scripter")


async def scripter_exec(page, code: str):
    """Paste and run code in Scripter."""
    f4 = (
        page.frame_locator('iframe[title="Plugin: Scripter"]')
        .frame_locator('iframe[name="Network Plugin Iframe"]')
        .frame_locator('iframe[name="Inner Plugin Iframe"]')
        .frame_locator('#iframe0')
    )
    await f4.locator('[title="New script"]').click(force=True)
    await page.wait_for_timeout(500)
    await f4.locator('.view-lines').click(force=True)
    await page.wait_for_timeout(300)
    await page.evaluate("(t) => navigator.clipboard.writeText(t)", code)
    await page.keyboard.press("Control+v")
    await page.wait_for_timeout(300)
    await f4.get_by_title("Run  (Ctrl+Return)").click()
    await page.wait_for_timeout(2000)
    await page.screenshot(path=str(SCREENSHOT_PATH), scale="css", type="png")

    # Read Scripter output (print() results)
    try:
        output_el = f4.locator('.output-lines, [class*=output], [class*=message]')
        count = await output_el.count()
        if count > 0:
            text = await output_el.first.inner_text()
            if text.strip():
                output_path = DIR / "output.txt"
                output_path.write_text(text.strip())
    except Exception:
        pass


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
        for attempt in range(3):
            await page.keyboard.press("Control+/")
            await page.wait_for_timeout(1000)
            await page.keyboard.type("Scripter", delay=50)
            await page.wait_for_timeout(1000)
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
            try:
                await scripter_exec(page, code)
                print(f"OK → {SCREENSHOT_PATH}")
            except Exception as e:
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
    timeout = 360 if manual_login else 150
    deadline = time.time() + timeout

    print(
        f"starting server (budget {timeout}s); tail log with: tail -f {LOG_PATH}",
        file=sys.stderr,
    )

    while time.time() < deadline:
        text = LOG_PATH.read_text() if LOG_PATH.exists() else ""
        if "Scripter opened." in text:
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
