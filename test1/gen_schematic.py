#!/usr/bin/env python3
"""KiCad schematic generator for test1 (Bobcat carrier board) — entry point.

The real work lives in the `gen/` package:
  gen/config.py        — paths, sheet/uid/LA tables, footprint constants
  gen/symbols.py       — symbol embedding, pin coord extraction
  gen/shared.py        — Sheet container, primitives, place(), sheet_block()
  gen/build_<sheet>.py — one builder per child sheet (+ build_root)

This file just stitches them together: writes the .kicad_pro, renders each
sheet, validates via kicad-cli sch export svg. UUIDs are derived
deterministically from a project namespace so re-runs produce stable files
(good for git diffs).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from gen import (
    build_bias,
    build_bobcat,
    build_connectors,
    build_eeprom,
    build_fmc,
    build_power,
    build_root,
)
from gen.config import (
    KICAD_CLI,
    OUT_DIR,
    PAGE_NUMBERS,
    PROJECT_NAME,
    RENDER_DIR,
    ROOT_UUID,
    SHEET_NAMES,
    SHEET_TITLES,
    SHEET_UUIDS,
)
from gen.layout_lint import lint, print_report, severity_counts
from gen.shared import Sheet


def project_json() -> str:
    sheets = [f'    ["{ROOT_UUID}", ""]']
    for n in SHEET_NAMES:
        sheets.append(f'    ["{SHEET_UUIDS[n]}", "{SHEET_TITLES[n]}"]')
    sheets_str = ",\n".join(sheets)
    return f'''{{
  "meta": {{
    "filename": "{PROJECT_NAME}.kicad_pro",
    "version": 3
  }},
  "schematic": {{
    "legacy_lib_dir": "",
    "legacy_lib_list": []
  }},
  "sheets": [
{sheets_str}
  ],
  "text_variables": {{}}
}}
'''


def root_sheet_instances() -> str:
    """Override the default single-sheet instances block in root."""
    lines = [f'    (path "/" (page "{PAGE_NUMBERS["root"]}"))']
    for n in SHEET_NAMES:
        lines.append(
            f'    (path "/{SHEET_UUIDS[n]}" (page "{PAGE_NUMBERS[n]}"))'
        )
    return "  (sheet_instances\n" + "\n".join(lines) + "\n  )"


EESCHEMA_APP = "/Users/masonking/Downloads/kicad/build/eeschema/eeschema.app"


def refresh_eeschema(sheet_names: list[str], root_path: Path) -> None:
    """Reload the project in eeschema so on-disk changes are visible. Closes
    any of our sheets that are currently open, then opens the root schematic
    (`<project>.kicad_sch`) — the hierarchical entry point, from which any
    child sheet can be navigated to.

    eeschema on this dev build is single-document AND has no file-watcher:
    `open -a` on a file already shown won't reload it, so we drive Cmd+W via
    AppleScript first. macOS `keystroke` is delivered to the *focused* app
    globally (NOT redirected by `tell process`), so we explicitly raise
    eeschema to frontmost with a settle delay before sending Cmd+W —
    otherwise the keystroke lands on whichever terminal/IDE invoked us.

    No-op opt-out: pass `--no-reopen` on the command line.
    """
    if not sheet_names:
        sheet_names = []
    needles = [f"{n} " for n in sheet_names]
    as_list = "{" + ", ".join(f'"{n}"' for n in needles) + "}" if needles else "{}"
    # IMPORTANT: AppleScript `keystroke` sends a *global* virtual key event
    # that lands on whatever app is keyboard-focused at the moment of send.
    # `tell process "eeschema"` only scopes property reads; it does NOT redirect
    # keystrokes. So before any keystroke we explicitly raise eeschema to
    # frontmost via `set frontmost ... to true` and let focus settle (delay).
    # Without this, running from a terminal would send Cmd+W to the terminal
    # host (e.g. VSCode), closing tabs there — a known footgun.
    script = f"""
on run
    set targets to {as_list}
    set matched to {{}}
    tell application "System Events"
        if not (exists process "eeschema") then return ""
        -- Capture matching window names FIRST (without touching focus), so we
        -- can iterate over a stable snapshot and force focus deliberately.
        tell process "eeschema"
            set winNames to name of every window
        end tell
        repeat with wn in winNames
            repeat with t in targets
                if (wn as text) starts with t then
                    set end of matched to (wn as text)
                    exit repeat
                end if
            end repeat
        end repeat
        if (count of matched) is 0 then return ""
        -- Now focus eeschema once and process every matched window from there.
        tell application process "eeschema" to set frontmost to true
        delay 0.4
        repeat with wn in matched
            try
                tell process "eeschema"
                    set w to window (wn as text)
                    perform action "AXRaise" of w
                end tell
                delay 0.2
                -- Re-assert frontmost in case raising the window dropped focus
                tell application process "eeschema" to set frontmost to true
                delay 0.2
                tell process "eeschema"
                    keystroke "w" using {{command down}}
                end tell
                delay 0.4
                try
                    tell process "eeschema"
                        click button "Don't Save" of sheet 1 of front window
                    end tell
                on error
                    try
                        tell process "eeschema"
                            click button "Discard" of sheet 1 of front window
                        end tell
                    end try
                end try
            end try
        end repeat
    end tell
    set AppleScript's text item delimiters to ","
    return (matched as text)
end run
"""
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:
        print(f"  (eeschema close skipped: {e}; will still try to open root)")
    # Always (re)open the project root — single source of truth for the
    # hierarchy. If eeschema is already running, the prior close above means
    # this `open` reloads the file; if not, it cold-launches eeschema.
    subprocess.run(["open", "-a", EESCHEMA_APP, str(root_path)])
    print(f"  opened in eeschema: {root_path.name}")


def validate(sch_path: Path, pages: str | None = None) -> tuple[bool, str]:
    """Run kicad-cli sch export png as a parse check + a viewable render.
    PNG export is dual-purpose: it parses the schematic (any malformed s-expr
    fails) AND emits a rendered image into kicad/render/<sheet>.png. The LLM
    loop can Read those PNGs directly to spot visual issues without a
    user-side round-trip through eeschema.

    pages: optional kicad-cli --pages value. Use "1" on the root sheet so
    kicad-cli renders only the title page, not every hierarchical child
    (children are rendered separately under their own filenames)."""
    cmd = [KICAD_CLI, "sch", "export", "png",
           "--output", str(RENDER_DIR),
           "--dpi", "150"]
    if pages:
        cmd += ["--pages", pages]
    cmd.append(str(sch_path))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return False, f"kicad-cli not at {KICAD_CLI}"
    ok = (r.returncode == 0) and "Done" in (r.stdout + r.stderr)
    return ok, (r.stdout + r.stderr).strip()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)

    # Project file
    (OUT_DIR / f"{PROJECT_NAME}.kicad_pro").write_text(project_json())
    print(f"wrote {PROJECT_NAME}.kicad_pro")

    # Root sheet — override the trailing single-page sheet_instances with multi-page
    root = build_root()
    root_text = root.render()
    root_text = root_text.replace(
        f'  (sheet_instances\n    (path "/" (page "{PAGE_NUMBERS["root"]}"))\n  )',
        root_sheet_instances(),
    )
    root_path = OUT_DIR / f"{PROJECT_NAME}.kicad_sch"
    root_path.write_text(root_text)
    print(f"wrote {root_path.name}")

    # Real child sheets (filled-in) override stubs.
    real_builders = {
        "eeprom": build_eeprom,
        "power": build_power,
        "connectors": build_connectors,
        "bias": build_bias,
        "bobcat": build_bobcat,
        "fmc": build_fmc,
    }
    sheet_issues: dict[str, list] = {}
    for n in SHEET_NAMES:
        cpath = OUT_DIR / f"{n}.kicad_sch"
        if n in real_builders:
            sheet = real_builders[n]()
            cpath.write_text(sheet.render())
            sheet_issues[n] = lint(sheet)
            counts = severity_counts(sheet_issues[n])
            print(f"wrote {n}.kicad_sch — lint: "
                  f"{counts['ERROR']}E/{counts['WARNING']}W/{counts['INFO']}I")
        else:
            stub = Sheet(name=n, uuid=SHEET_UUIDS[n], page=PAGE_NUMBERS[n],
                         title=f"{PROJECT_NAME} — {SHEET_TITLES[n]}").render()
            cpath.write_text(stub)
            print(f"wrote {n}.kicad_sch (stub)")

    # Validate root + every child via kicad-cli (parse gate).
    # On the root, restrict rendering to page 1 so kicad-cli does not also
    # emit "test1-<SheetTitle>.png" duplicates for every child sheet.
    failures = 0
    targets = [(root_path, "1")] + [(OUT_DIR / f"{n}.kicad_sch", None) for n in SHEET_NAMES]
    for path, pages in targets:
        ok, msg = validate(path, pages=pages)
        flag = "OK " if ok else "FAIL"
        print(f"  [{flag}] {path.name}: {msg.splitlines()[-1] if msg else ''}")
        if not ok:
            failures += 1
            print(msg)

    # Layout lint summary — advisory only, does not affect exit code.
    print()
    print("===== Layout lint =====")
    total = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for n, issues in sheet_issues.items():
        print_report(n, issues)
        for k, v in severity_counts(issues).items():
            total[k] += v
    print(f"total: {total['ERROR']} ERROR, {total['WARNING']} WARNING, "
          f"{total['INFO']} INFO")

    # Always (re)open the project root in eeschema so the user sees the
    # freshly-regenerated hierarchy. Opt out with `--no-reopen`.
    if "--no-reopen" not in sys.argv:
        root_sch_path = OUT_DIR / f"{PROJECT_NAME}.kicad_sch"
        refresh_eeschema(list(SHEET_NAMES) + [PROJECT_NAME], root_sch_path)

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
