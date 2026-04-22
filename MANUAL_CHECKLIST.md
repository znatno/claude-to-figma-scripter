# Manual verification checklist

Quick eyeball checks to confirm the fixes in `run.py` are still doing their job.
No browser automation — you run a script, watch the log, look at the canvas.

Tail the log in a second terminal before each check:

```
tail -f /tmp/claude-figma.log
```

---

## 1. Grey-rectangle paste can no longer happen

Goal: prove there is no clipboard→canvas fallback.

- Run any normal script via `bin/figma-run some.js`.
- In the log, you should see ONE of these patterns — never both, never neither:
  - **Success:** `[write] ok — …` then `[verify] ok — …` then `[focus] ok — …` then `[run] Cmd+Enter dispatched`.
  - **Safe abort:** `[write] FAIL — …` then `[run] ABORT — editor write failed after one reopen…` and `STATUS=error`.
- The log must NEVER say "falling back to keyboard paste" — that line was removed. If you see it, something is wrong.
- On a safe abort, look at the Figma canvas: it should NOT have a new frame/rectangle. Scripter stays open; the server stays alive for your next command.

## 2. Random mid-session page switching

Goal: confirm that running scripts does not cause Figma to change pages.

- Open a file with several pages. Navigate to a specific page manually.
- Run 3–5 scripts in a row via `bin/figma-run`.
- After each run, the canvas should still be on the same page you started on.
- The initial startup node-id jump (when your URL has `?node-id=…`) is still on by default and is expected — that only fires once, at server start.

## 3. Wrong-tab execution

Goal: confirm we only ever write to the visible Scripter tab.

- In Scripter, open a second tab (click the `+` in Scripter). Put obviously different code in it.
- Switch back to your main tab.
- Run a script via `bin/figma-run`.
- Log should say `[write] ok — N chars → visible Monaco editor (of 2 total)`.
- The second tab's contents must be unchanged — only the visible one gets overwritten.
- If the tool can't tell which tab is visible (or sees more than one visible), log shows `[write] FAIL — multiple-visible-editors` or `no-visible-editor` and the run is aborted. No guessing.

## 4. Focus can't leak to canvas

Goal: confirm `Cmd+Enter` never fires unless focus is in the Scripter editor.

- Run a normal script. Log must show `[focus] ok — textarea.inputarea inside Scripter iframe has focus` right before `[run] Cmd+Enter dispatched`.
- If you ever see `[focus] FAIL — …` followed by `[run] ABORT — …`, that is correct defensive behavior: the keystroke was suppressed, nothing leaked.

## 5. Output capture source is labelled

Every successful run ends with: `[output] source=console, status=ok, len=…` (or `source=dom`). If you ever see `source=none` with `status=ok`, that's a contradiction — report it.

---

## What the log prefixes mean

| Prefix     | Meaning                                                   |
|------------|-----------------------------------------------------------|
| `[write]`  | Monaco `setValue` on the visible editor                   |
| `[verify]` | Read-back of the visible `.view-lines` DOM vs source      |
| `[focus]`  | `document.activeElement` check before `Cmd+Enter`         |
| `[run]`    | The `Cmd+Enter` keystroke was dispatched (or aborted)     |
| `[output]` | Where captured text came from (console bridge vs DOM scrape) |

If any step fails, the run aborts with `STATUS=error` and Scripter is left open so you can inspect the state.
