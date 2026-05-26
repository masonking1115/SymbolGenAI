# test1 GUI

Local web app for the test1 (Bobcat carrier) schematic pipeline. FastAPI
backend wraps `gen_schematic.py` / `run_review.py` as subprocesses and
streams output over SSE; the React frontend matches the visual style of
the reference checklist tool — left rail nav, top toolbar, optional
split-pane PNG view.

## What's wired today

- **Schematic Generator tab** — full behavior end-to-end. Click *Generate
  schematic*, watch console stream in real time, see the linter checklist
  populate per rule with pass/fail and per-issue detail, then the PNG
  pane refreshes automatically (cache-busted on mtime).
- **Design Review tab** — run review, run review + autofix-trivial,
  findings list, full `error_log.md` viewer. After a successful autofix
  it bounces back to the Generator tab so you can re-lint.
- **Library tab** — lists every part under `Parts Library/<MPN>/`, shows
  which have datasheets / fingerprints / generated symbols, with filter
  chips and a stubbed *Generate symbol* action.
- **PNG split view** — toggle on/off from the top bar; switch sheets with
  arrows or chips; zoom controls.

## Run it

Two processes — backend and Vite dev server.

```bash
# 1. backend (port 8765)
cd test1/gui/backend
pip install -r requirements.txt   # one time
python app.py

# 2. frontend (port 5173, proxies /api → 8765)
cd test1/gui/frontend
npm install                       # one time
npm run dev
```

Open <http://localhost:5173>.

## Layout

```
backend/
  app.py            FastAPI app + SSE streaming for run output
  requirements.txt
frontend/
  index.html, vite.config.ts, tailwind/postcss configs
  src/
    main.tsx, App.tsx     shell + tab routing
    api.ts                fetch + EventSource client
    types.ts
    components/
      Sidebar.tsx, TopBar.tsx, PngViewer.tsx
      Console.tsx, Icon.tsx
    tabs/
      Generator.tsx       phase 2 — full behavior
      Library.tsx         phase 1 — listing + detail
      Review.tsx          phase 3 — run + autofix + log
```

## Notes

- Backend always passes `--no-reopen` to `gen_schematic.py` so the
  AppleScript-driven eeschema reload never fires from the server.
- `/api/file` allow-lists `netlist/`, `design_requirements.md`,
  `Voltai_Notes.md`, `error_log.md`, and `review/semantic_findings.json`
  so the GUI can edit YAML + requirements without exposing the rest of
  the project.
- The lint report is parsed from `gen_schematic.py` stdout, not by
  importing the linter module. Cheap, but means the GUI shows only what
  the script actually printed.
- Concurrent runs aren't blocked, but the scripts assume serial use.
- Library tab's *Generate symbol* button is intentionally a stub — the
  per-IC ingester / fingerprint pipeline lives outside this GUI for now.
```
