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


def validate(sch_path: Path) -> tuple[bool, str]:
    """Run kicad-cli sch export png as a parse check + a viewable render.
    PNG export is dual-purpose: it parses the schematic (any malformed s-expr
    fails) AND emits a rendered image into kicad/render/<sheet>.png. The LLM
    loop can Read those PNGs directly to spot visual issues without a
    user-side round-trip through eeschema."""
    cmd = [KICAD_CLI, "sch", "export", "png",
           "--output", str(RENDER_DIR),
           "--dpi", "150",
           str(sch_path)]
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
    failures = 0
    for path in [root_path] + [OUT_DIR / f"{n}.kicad_sch" for n in SHEET_NAMES]:
        ok, msg = validate(path)
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

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
