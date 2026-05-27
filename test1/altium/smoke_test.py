"""Gate 0 smoke test for the KiCad -> Altium backend migration.

Proves, end to end and in-process, that altium_monkey can stand in for the
KiCad generator's seams:

  1. author a .SchLib symbol library          (<- gen generating .kicad_sym)
  2. author a .PcbLib footprint library        (<- the .pretty libraries)
  3. build a .SchDoc that exercises EVERY primitive AltiumSheet emits:
     place (with pin-coord readback), wire, junction, net_label, power_at,
     port, no_connect, text
  4. round-trip: reopen the saved .SchDoc and assert objects survived
  5. render the .SchDoc to SVG (the parse gate, == `kicad-cli sch export svg`)

The one thing this cannot self-verify is "opens uncorrupted in REAL Altium" —
that is the manual gate left for the Windows Altium install.

Run:  python -m test1.altium.smoke_test     (from the repo root, in the venv)
"""

from __future__ import annotations

import sys

from altium_monkey import AltiumSchDoc, PortIOType, PortStyle

from .config import LIB_DIR, OUT_DIR, RENDER_DIR
from .footprints import author_footprint_lib
from .shared import AltiumSheet
from .symbols import author_passive_lib


def _check(label: str, ok: bool) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    return ok


def main() -> int:
    print("== Gate 0: KiCad -> Altium backend smoke test ==\n")
    failures = 0

    # --- Step 1+2: author libraries ---------------------------------------
    print("Step 1/2 — author SchLib + PcbLib")
    sch_lib = author_passive_lib(LIB_DIR / "smoke.SchLib")
    pcb_lib = author_footprint_lib(LIB_DIR / "smoke.PcbLib")
    failures += not _check(f"SchLib written ({sch_lib.name})", sch_lib.exists())
    failures += not _check(f"PcbLib written ({pcb_lib.name})", pcb_lib.exists())

    # --- Step 3: build a schematic exercising every primitive -------------
    print("\nStep 3 — build .SchDoc exercising all primitives")
    sheet = AltiumSheet(name="smoke", title="Gate 0 Smoke")

    # Place the IC and a decoupling cap; read their pin world coords back.
    u1 = sheet.place(sch_lib, "IC8", "U1", "LDO_TEST", x=2000, y=4000)
    c1 = sheet.place(sch_lib, "CAP", "C1", "1uF", x=1200, y=4000)
    failures += not _check("place() returned U1 pin coords", set(u1) >= {"1", "8", "3"})
    failures += not _check("place() returned C1 pin coords", set(c1) == {"1", "2"})

    # VIN rail: cap pin1 -> U1 VIN(pin1), tied to +3V3 power port.
    vin_y = u1["1"][1]
    sheet.wire(c1["1"][0], c1["1"][1], c1["1"][0], vin_y)
    sheet.wire(c1["1"][0], vin_y, u1["1"][0], vin_y)
    sheet.junction(c1["1"][0], vin_y)
    sheet.power_at("+3V3", c1["1"][0], vin_y + 200)
    sheet.wire(c1["1"][0], vin_y, c1["1"][0], vin_y + 200)

    # GND: cap pin2 + U1 GND(pin3) -> GND power port.
    sheet.wire(c1["2"][0], c1["2"][1], c1["2"][0], 3400)
    sheet.power_at("GND", c1["2"][0], 3400)

    # VOUT off-sheet port + net label.
    sheet.net_label("VOUT", u1["8"][0] + 100, u1["8"][1])
    sheet.wire(u1["8"][0], u1["8"][1], u1["8"][0] + 400, u1["8"][1])
    sheet.port("VOUT", u1["8"][0] + 400, u1["8"][1],
               io=PortIOType.OUTPUT, style=PortStyle.RIGHT)

    # Unused pin -> no-connect; plus a design note.
    sheet.no_connect(*u1["4"])
    sheet.text("Gate 0 smoke: every AltiumSheet primitive exercised", 1000, 4800)

    out_sch = sheet.save(OUT_DIR / "smoke.SchDoc")
    failures += not _check(f".SchDoc written ({out_sch.name})", out_sch.exists())

    # --- Step 4: round-trip -----------------------------------------------
    print("\nStep 4 — reopen and verify objects survived")
    re = AltiumSchDoc(out_sch)
    failures += not _check(f"components == 2 (got {len(re.components)})", len(re.components) == 2)
    failures += not _check(f"wires >= 5 (got {len(re.wires)})", len(re.wires) >= 5)
    failures += not _check(f"net_labels >= 1 (got {len(re.net_labels)})", len(re.net_labels) >= 1)
    failures += not _check(f"power_ports == 2 (got {len(re.power_ports)})", len(re.power_ports) == 2)
    failures += not _check(f"ports == 1 (got {len(re.ports)})", len(re.ports) == 1)

    # --- Step 5: render SVG (parse gate) ----------------------------------
    print("\nStep 5 — render SVG (parse gate)")
    svg = sheet.render_svg(RENDER_DIR / "smoke.svg")
    svg_ok = svg.exists() and svg.stat().st_size > 500 and "<svg" in svg.read_text(encoding="utf-8")[:200]
    failures += not _check(f"SVG rendered ({svg.stat().st_size} bytes)", svg_ok)

    print("\n" + ("=" * 48))
    if failures == 0:
        print("Gate 0 PASSED (in-process). Manual gate remaining:")
        print(f"  Open {out_sch} in real Altium and confirm it is uncorrupted.")
        return 0
    print(f"Gate 0 FAILED — {failures} check(s) failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
