# Project Manual: claude-to-figma-scripter

This project enables AI-driven Figma design automation. It allows an AI (like Gemini) to design, manipulate, and automate Figma canvases by writing and executing JavaScript via the [Figma Scripter plugin](https://www.figma.com/community/plugin/757836922707087381) or a custom alternative.

---

## 1. Core Architecture

The system operates as a bridge between your terminal and the Figma canvas:

1.  **`run.py` (The Server):** A Python script using **Playwright** to launch a Firefox instance, log into Figma, and manage the Scripter plugin.
2.  **The Fifo (`/tmp/claude-figma.fifo`):** A named pipe used for Inter-Process Communication (IPC). You send scripts to this pipe, and `run.py` (which is listening) injects them into Figma.
3.  **Figma Scripter:** The environment inside Figma where the [Plugin API](https://www.figma.com/plugin-docs/) code is executed.
4.  **Feedback Loop:** After each run, the system captures console output (`print()` calls) into `output.txt` and takes a screenshot of the result in `result.png`.

---

## 2. Setup & Requirements

- **Python 3.10+**
- **Playwright:** `pip install playwright && playwright install firefox`
- **Figma Account:** With the [Scripter plugin](https://www.figma.com/community/plugin/757836922707087381) installed.

---

## 3. Usage Modes

### A. One-Off Scripting (The Scripter Loop)
The primary way to interact with Figma.

- **Inline Command:**
  ```bash
  python run.py "figma.createRectangle()"
  ```
- **From a File:**
  ```bash
  python run.py --file path/to/script.js
  ```
- **Using the Wrapper (`bin/figma-run`):**
  This script handles server restarts and output printing automatically:
  ```bash
  ./bin/figma-run path/to/script.js
  ```

### B. Specialized Pipelines
The project includes structured workflows for common design tasks:

1.  **Component Pipeline (`add-component.md`):**
    - **Step 1:** Generate the visual nodes.
    - **Step 2:** Bind nodes to Figma Variables (colors, spacing, radii) and Text Styles.
2.  **PDF Import (`pdf-import.md`):**
    - Analyzes PDF slides and reconstructs them as editable Figma frames (1920x1080).
3.  **Comment Handling (`figma-comments.md`):**
    - Uses the Figma REST API to fetch unresolved comments and applies fixes to the canvas automatically.

### C. Hybrid Plugin Invocations
You can trigger other Figma plugins via `run.py`:
- **Command:** `python run.py "__plugin__:Propstar > Create property table"`
- This allows you to combine custom scripting with community tools like **Propstar**.

### D. Custom Plugin Alternative (`plugin/`)
The `plugin/` directory contains a minimal, custom-built Figma plugin.
- **Why?** It's a lightweight alternative to Scripter for users who want a dedicated, stripped-down script execution environment.
- **Components:** `code.js` (backend), `ui.html` (frontend), `manifest.json` (config).
- *Note:* This requires manual installation in Figma and minor configuration in `run.py` to target it instead of Scripter.

---

## 4. Key Execution Principles

- **Atomic Components:** Build complex UIs from smaller, reusable instances.
- **Variable Binding:** Always prefer binding colors and sizes to Figma Variables rather than hardcoding.
- **Verification:** Always end scripts with a `print()` statement summarizing the result (e.g., `print("built: Frame 1200x800 with 5 buttons")`).
- **Visual Check:** Consult `result.png` only when manual visual verification is required.
