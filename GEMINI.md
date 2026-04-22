# GEMINI.md - Project Context & Instructions

This project, **claude-to-figma-scripter**, is an AI-driven automation framework that enables LLMs to design and manipulate Figma canvases by executing JavaScript via the [Figma Scripter plugin](https://www.figma.com/community/plugin/757836922707087381).

---

## Project Overview

- **Core Purpose:** Bridge the gap between AI coding assistants and the Figma Plugin API.
- **Main Technologies:** Python 3.10+, Playwright (Firefox), JavaScript (Figma Plugin API).
- **Architecture:** 
    - `run.py` acts as a Playwright server that launches a browser, logs into Figma, and listens on a named pipe (`/tmp/claude-figma.fifo`).
    - `bin/figma-run` is a wrapper script for sending JS files/commands to the server and capturing output.
    - Scripts are executed within the Figma Scripter plugin environment.

---

## Building and Running

### Setup
1.  **Environment:** Ensure you are using the provided virtual environment: `source .venv/bin/activate`.
2.  **Dependencies:** `pip install playwright && playwright install firefox`.
3.  **Figma Login:** The server handles authentication. If `.auth-state.json` is missing, it will prompt for manual login or use provided credentials.

### Key Commands
- **Start/Ensure Server:** `python run.py --ensure "FIGMA_FILE_URL"` (Idempotent).
- **Run a Script:** `./bin/figma-run script.js` (Captures `print()` output).
- **Restart Server:** `./bin/figma-run --restart "FIGMA_FILE_URL"`.
- **Run Background Server:** `python run.py --serve "FIGMA_FILE_URL"` (Blocking).
- **Invoke Plugins:** `python run.py "__plugin__:Propstar > Create property table"`.

---

## Development Conventions & Pipelines

### 1. Scripter Rules (Crucial for Stability)
- **Load Fonts First:** Always `await figma.loadFontAsync()` before any text operation.
- **Append Before Set:** Always `appendChild()` a node to the scene tree *before* setting its properties (resize, layout, etc.).
- **Auto Layout Order:** Set `layoutMode` *before* any other Auto Layout properties (itemSpacing, padding).
- **Colors:** Use RGB 0–1 objects (e.g., `{r: 0, g: 0.5, b: 1}`), NOT hex strings.

### 2. Verification & Changelog Strategy
- **Text Over Screenshots:** Prioritize `print()` statements for structural verification (e.g., `print("built: Frame 1200x800")`). It is more token-efficient and accurate than analyzing `result.png`.
- **Changelog:** After every code or documentation change (besides editing this file or `changelog.md`), you **MUST** record it in `changelog.md` under the `## [Unreleased]` header.
- **Result Snapshot:** `result.png` is updated after every run but should be used primarily for visual "vibe" checks.

### 3. Specialized Pipelines
- **Component Addition (`add-component.md`):** A two-step process. Step 1: Create visual structure with hardcoded colors. Step 2: Bind nodes to Figma Variables and Text Styles.
- **PDF Import (`pdf-import.md`):** Analyzes PDF slides and reconstructs them as editable 1920x1080 Figma frames.
- **Comment Fixer (`figma-comments.md`):** Fetches unresolved comments via Figma REST API and applies fixes programmatically.

---

## Key Files Summary

- `run.py`: The heart of the automation; manages browser and IPC.
- `scripter.md`: The definitive ruleset for writing crash-free Figma scripts.
- `CLAUDE.md`: Detailed session-specific instructions and environment map.
- `AGENTS.md`: High-level guide for AI agents using this project.
- `manual/USAGE.md`: Human-readable guide for project utilization.
- `plugin/`: Source for a custom, lightweight alternative to the Scripter plugin.
