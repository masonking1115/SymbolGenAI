# test1 GUI

Local web app for the Bobcat carrier schematic pipeline. A FastAPI backend
drives the **Altium** generator (`python -m test1.altium.build_project`) and the
review pass as subprocesses and streams their output over SSE; the React/Vite
frontend renders the sheets, the linter checklist, and the chat/review panes.

## What's wired today

- **Schematic Generator tab** — click *Generate*, watch the build stream in real
  time, see the linter checklist populate per rule (from `out/lint.json`) with
  pass/fail and per-issue detail, then the sheet preview refreshes
  automatically (cache-busted on mtime).
- **Design Review tab** — run review, run review + autofix-trivial, findings
  list, full `error_log.md` viewer. After a successful autofix it bounces back to
  the Generator tab so you can re-lint. Uploading a review PDF parses it into
  `review/findings.json`; clicking *Apply* parks a request in
  `review/fix_queue.json` for the agent (see the `review-fix-queue` skill).
- **Library tab** — lists every part under `Parts Library/<MPN>/`, shows which
  have datasheets / footprints / symbols, renders the symbol SVG, surfaces the
  Ultra Librarian deep-link, and accepts a `.SchLib` upload.
- **Design Resources tab** — datasheets, design-requirements, and skills
  (markdown CRUD under `test1/resources/`).
- **Simulation tab** — ngspice-backed test-block catalog + results.
- **Sheet preview** — toggle the split view; switch sheets; zoom. Renders the
  altium_monkey SVG (or a rasterized PNG).

## Run it

Two processes — backend and Vite dev server. Use the **spike venv** interpreter
for the backend (it has `altium-monkey` + the build deps):

```powershell
# 1. backend (port 8765)
C:\Users\mking\Downloads\altium_spike\.venv\Scripts\python.exe test1\gui\backend\app.py

# 2. frontend (port 5173, proxies /api -> 8765)
cd test1\gui\frontend
npm install          # one time
npm run dev
```

Open <http://localhost:5173>. Build/verify the frontend with the **local**
binaries: `./node_modules/.bin/tsc --noEmit -p .` then
`./node_modules/.bin/vite build` (a global `tsc` pulls the wrong package).

## Layout

```
backend/
  app.py            FastAPI app + SSE streaming for run output
  agent.py          drives `claude -p` for chat / apply / sim
  requirements.txt  (fastapi, uvicorn, pydantic — altium-monkey comes from the venv)
frontend/
  index.html, vite.config.ts, tailwind/postcss configs
  src/
    main.tsx, App.tsx     shell + tab routing + pipeline-stage state
    api.ts                fetch + EventSource client
    types.ts
    components/           Sidebar, TopBar, PngViewer, AgentRail, Splitter, ...
    tabs/                 Generator, Library, Resources, Review, Simulation
```

## Notes

- The backend runs the generator with the spike-venv interpreter and forces
  `PYTHONUTF8`/`PYTHONIOENCODING=utf-8` on the subprocess, so a non-ASCII glyph
  in a sheet annotation can't crash the build with a Windows cp1252
  `UnicodeEncodeError`.
- The lint report is read from `out/lint.json` (written by `build_project`);
  parsing the run stdout is only a fallback.
- `/api/file` allow-lists `netlist/`, `design_requirements.md`, `error_log.md`,
  and `review/semantic_findings.json` so the GUI can edit the YAML + requirements
  without exposing the rest of the project. Keep this list tight.
- Run state is an **in-memory** registry — restarting the backend drops run
  history. Concurrent runs aren't blocked, but the scripts assume serial use.
- The SSE run stream sends a `done` event even to a subscriber that connects
  *after* the process finishes, so the GUI never hangs on a fast build.
