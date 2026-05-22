# Symbol Library AI — Schematic Editor MVP

An Electron + React + TypeScript schematic design environment, the first
milestone of the Symbol Library AI Copilot described in [SymbolGenAI.md](SymbolGenAI.md).

This milestone delivers the EDA canvas: a built-in symbol palette, drag/click
placement, selection and rotation, and Altium-style orthogonal wire routing
with pin snapping. Later milestones will add datasheet parsing, the SQLite
symbol library, and the Claude chat copilot.

## Stack

- Electron 30 (desktop shell)
- React 18 + TypeScript 5
- Vite 5 (renderer dev server + build)
- Zustand (canvas state)
- SVG-based schematic canvas (no third-party canvas lib)

## Run

```sh
npm install
npm run dev          # launches Vite + Electron together
```

To iterate in a regular browser tab (no Electron):

```sh
npm run dev:web      # then open http://localhost:5173
```

To produce a production build:

```sh
npm run build        # compiles main process + bundles renderer
npm start            # runs Electron against the built renderer
```

## Layout

```
electron/                   Main process + preload (Node side)
src/
  components/               Editor, Canvas, Palette, Toolbar, etc.
  lib/
    geometry.ts             Grid / snap / rotation / Manhattan helpers
    symbolLibrary.tsx       Built-in symbol catalog (resistor, cap, etc.)
  store/schematicStore.ts   Zustand store with all editor state
  styles/app.css            Theme
  types/schematic.ts        Shared data model
```

The data model is intentionally serializable JSON (no class instances) so the
schematic can be persisted to SQLite or sent through Claude tool calls in the
next milestones without changes.

## Editor controls

| Action | How |
| --- | --- |
| Place a symbol | Click in palette → click on canvas (place multiple, press <kbd>Esc</kbd> to stop) |
| Select | Click a symbol, wire, or pin (Shift to add) |
| Move | Drag a selected symbol |
| Rotate | <kbd>R</kbd> (rotates the placement ghost or current selection) |
| Delete | <kbd>Del</kbd> / <kbd>Backspace</kbd> |
| Draw wire | Press <kbd>W</kbd> (or click a pin) → click corners → click target pin |
| Flip wire bend | <kbd>Tab</kbd> while drawing |
| Cancel wire | <kbd>Esc</kbd> or right-click |
| Pan | Middle-mouse drag, or hold <kbd>Space</kbd> + drag, or pick the Pan tool |
| Zoom | Scroll wheel (zooms toward cursor) |
| Reset view | Toolbar → Reset view |

## What's in the symbol library

The built-in catalog ships with the common Altium-style passives and a few
active parts to verify placement and routing end-to-end:

- Passive: Resistor, Capacitor, Inductor
- Active: Diode, LED, NPN BJT, PNP BJT
- Power: Ground, VCC
- Connector: 1×2 Header

These are defined in [`src/lib/symbolLibrary.tsx`](src/lib/symbolLibrary.tsx)
as plain `SymbolDefinition` records — SVG body plus pin coordinates — which
is the same shape the AI symbol generator will emit in a later milestone.

## Roadmap (later milestones)

1. SQLite-backed library: persistent storage, categories, search, versioning.
2. Datasheet parser: PDF text extraction → pin table → `SymbolDefinition`.
3. Claude chat copilot: query, modify, recommend symbols and formatting.
4. ERC / netlist export: validate connections, emit BOM + netlist.
5. PCB footprint linkage.
