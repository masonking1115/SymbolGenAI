#!/usr/bin/env python3
"""Generate LDO_LNA_Demo.kicad_sch — LNA + LDO application circuits with
LNA RF_OUT wired to LDO VIN, all on one A3 sheet."""

import json
import uuid
from pathlib import Path

ROOT = Path("/Users/masonking/Downloads/SymbolLibraryAI/LDO_LNA_Demo")
PROJ = "LDO_LNA_Demo"
SCH_UUID = "b1f00f00-1234-4abc-9def-1111aaaa2222"

def u():
    return str(uuid.uuid4())

# ---------------------------------------------------------------------------
# Embedded library symbols (Device:R/C/L, power:GND, power:+3V3, and our two ICs)
# ---------------------------------------------------------------------------

def read_ic_symbol(path: Path, name: str) -> str:
    """Extract the (symbol "X" ... ) block from a .kicad_sym, rename to Lib:X."""
    text = path.read_text()
    start = text.find(f'(symbol "{name}"')
    assert start >= 0, f"can't find symbol {name} in {path}"
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
        i += 1
    block = text[start:end]
    # Rename "X" to "Lib:X" (the lib name we'll use in lib_id)
    block = block.replace(f'(symbol "{name}"', f'(symbol "{name}:{name}"', 1)
    return block

LNA_LIB = read_ic_symbol(ROOT.parent / "SKY67150-396LF.kicad_sym", "SKY67150-396LF")
LDO_LIB = read_ic_symbol(ROOT.parent / "TPS7E72.kicad_sym", "TPS7E72")

DEVICE_R = '''(symbol "Device:R"
		(pin_numbers (hide yes))
		(pin_names (offset 0))
		(exclude_from_sim no) (in_bom yes) (on_board yes)
		(property "Reference" "R" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
		(property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
		(property "Footprint" "" (at -1.778 0 90) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Description" "Resistor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "ki_keywords" "R res resistor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "ki_fp_filters" "R_*" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(symbol "R_0_1"
			(rectangle (start -1.016 -2.54) (end 1.016 2.54)
				(stroke (width 0.254) (type default)) (fill (type none))))
		(symbol "R_1_1"
			(pin passive line (at 0 3.81 270) (length 1.27)
				(name "~" (effects (font (size 1.27 1.27))))
				(number "1" (effects (font (size 1.27 1.27)))))
			(pin passive line (at 0 -3.81 90) (length 1.27)
				(name "~" (effects (font (size 1.27 1.27))))
				(number "2" (effects (font (size 1.27 1.27))))))
		(embedded_fonts no))'''

DEVICE_C = '''(symbol "Device:C"
		(pin_numbers (hide yes))
		(pin_names (offset 0.254))
		(exclude_from_sim no) (in_bom yes) (on_board yes)
		(property "Reference" "C" (at 0.635 2.54 0) (effects (font (size 1.27 1.27)) (justify left)))
		(property "Value" "C" (at 0.635 -2.54 0) (effects (font (size 1.27 1.27)) (justify left)))
		(property "Footprint" "" (at 0.9652 -3.81 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Description" "Unpolarized capacitor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "ki_keywords" "cap capacitor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "ki_fp_filters" "C_*" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(symbol "C_0_1"
			(polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762))
				(stroke (width 0.508) (type default)) (fill (type none)))
			(polyline (pts (xy -2.032 0.762) (xy 2.032 0.762))
				(stroke (width 0.508) (type default)) (fill (type none))))
		(symbol "C_1_1"
			(pin passive line (at 0 3.81 270) (length 2.54)
				(name "~" (effects (font (size 1.27 1.27))))
				(number "1" (effects (font (size 1.27 1.27)))))
			(pin passive line (at 0 -3.81 90) (length 2.54)
				(name "~" (effects (font (size 1.27 1.27))))
				(number "2" (effects (font (size 1.27 1.27))))))
		(embedded_fonts no))'''

DEVICE_L = '''(symbol "Device:L"
		(pin_numbers (hide yes))
		(pin_names (offset 1.016))
		(exclude_from_sim no) (in_bom yes) (on_board yes)
		(property "Reference" "L" (at -1.27 0 90) (effects (font (size 1.27 1.27))))
		(property "Value" "L" (at 1.905 0 90) (effects (font (size 1.27 1.27))))
		(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Description" "Inductor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "ki_keywords" "inductor coil choke" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "ki_fp_filters" "Choke_* L_*" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(symbol "L_0_1"
			(arc (start 0 -2.54) (mid 0.635 -1.905) (end 0 -1.27) (stroke (width 0) (type default)) (fill (type none)))
			(arc (start 0 -1.27) (mid 0.635 -0.635) (end 0 0) (stroke (width 0) (type default)) (fill (type none)))
			(arc (start 0 0) (mid 0.635 0.635) (end 0 1.27) (stroke (width 0) (type default)) (fill (type none)))
			(arc (start 0 1.27) (mid 0.635 1.905) (end 0 2.54) (stroke (width 0) (type default)) (fill (type none))))
		(symbol "L_1_1"
			(pin passive line (at 0 3.81 270) (length 1.27)
				(name "~" (effects (font (size 1.27 1.27))))
				(number "1" (effects (font (size 1.27 1.27)))))
			(pin passive line (at 0 -3.81 90) (length 1.27)
				(name "~" (effects (font (size 1.27 1.27))))
				(number "2" (effects (font (size 1.27 1.27))))))
		(embedded_fonts no))'''

POWER_GND = '''(symbol "power:GND"
		(power) (pin_names (offset 0))
		(exclude_from_sim no) (in_bom no) (on_board yes)
		(property "Reference" "#PWR" (at 0 -6.35 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Value" "GND" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
		(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Description" "Ground" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "ki_keywords" "global power" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(symbol "GND_0_1"
			(polyline (pts (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27))
				(stroke (width 0) (type default)) (fill (type none))))
		(symbol "GND_1_1"
			(pin power_in line (at 0 0 270) (length 0) (hide yes)
				(name "GND" (effects (font (size 1.27 1.27))))
				(number "1" (effects (font (size 1.27 1.27))))))
		(embedded_fonts no))'''

POWER_3V3 = '''(symbol "power:+3V3"
		(power) (pin_names (offset 0))
		(exclude_from_sim no) (in_bom no) (on_board yes)
		(property "Reference" "#PWR" (at 0 -3.81 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Value" "+3V3" (at 0 3.81 0) (effects (font (size 1.27 1.27))))
		(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Description" "Power symbol creates a global label with name \\"+3V3\\"" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "ki_keywords" "global power" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(symbol "+3V3_0_1"
			(polyline (pts (xy -0.762 1.27) (xy 0 2.54) (xy 0.762 1.27))
				(stroke (width 0) (type default)) (fill (type none)))
			(polyline (pts (xy 0 0) (xy 0 2.54))
				(stroke (width 0) (type default)) (fill (type none))))
		(symbol "+3V3_1_1"
			(pin power_in line (at 0 0 90) (length 0) (hide yes)
				(name "+3V3" (effects (font (size 1.27 1.27))))
				(number "1" (effects (font (size 1.27 1.27))))))
		(embedded_fonts no))'''

# ---------------------------------------------------------------------------
# Schematic content
# ---------------------------------------------------------------------------

# Symbol instances ----------------------------------------------------------
# tuple: (lib_id, ref, value, x, y, angle, footprint, datasheet, optional manufacturer)
# Property positions are computed inline below for IC parts; for passives we
# use the convention from the topology skill.

INSTANCES = []

def add_ic(lib_id, ref, value, x, y, footprint, datasheet, manufacturer, n_pins,
           ref_off=-12.7, val_off=-10.16):
    """Add an IC instance. ref_off/val_off are Y-offsets relative to the symbol
    origin (negative = above body in world coords)."""
    INSTANCES.append({
        "lib_id": lib_id, "ref": ref, "value": value, "x": x, "y": y, "angle": 0,
        "footprint": footprint, "datasheet": datasheet, "manufacturer": manufacturer,
        "n_pins": n_pins,
        "ref_pos": (x, y + ref_off),
        "val_pos": (x, y + val_off),
    })

def add_passive(lib_id, ref, value, x, y, angle, footprint, kind):
    """Add an R/C/L instance with label positions per topology skill."""
    if angle == 0:
        # Vertical: ref upper-right, value lower-right of body
        ref_pos = (x + 2.54, y - 1.27)
        val_pos = (x + 2.54, y + 1.27)
    else:
        # Horizontal: ref above body, value below
        ref_pos = (x, y - 3.81)
        val_pos = (x, y + 3.81)
    INSTANCES.append({
        "lib_id": lib_id, "ref": ref, "value": value, "x": x, "y": y, "angle": angle,
        "footprint": footprint, "datasheet": "~", "manufacturer": None,
        "n_pins": 2,
        "ref_pos": ref_pos, "val_pos": val_pos,
        "kind": kind,
    })

def add_power(lib_id, ref, value, x, y, angle=0):
    """Add a power symbol. Value is shown next to the symbol per offset baked
    into the embedded def, so we just set its 'at' to the symbol origin."""
    INSTANCES.append({
        "lib_id": lib_id, "ref": ref, "value": value, "x": x, "y": y, "angle": angle,
        "footprint": "", "datasheet": "", "manufacturer": None,
        "n_pins": 1, "is_power": True,
    })

# LNA U1 at (100.33, 127.0) — pin 9 EP at (100.33, 137.16)
add_ic("SKY67150-396LF:SKY67150-396LF", "U1", "SKY67150-396LF",
       100.33, 127.0,
       "Package_DFN_QFN:DFN-8-1EP_2x2mm_P0.5mm_EP0.85x1.7mm",
       "https://www.skyworksinc.com/-/media/SkyWorks/Documents/Products/2001-2100/SKY67150-396LF.pdf",
       "Skyworks Solutions", n_pins=9, ref_off=-12.7, val_off=-10.16)

# LDO U2 at (256.54, 127.0) — pin 2 GND at (256.54, 134.62)
add_ic("TPS7E72:TPS7E72", "U2", "TPS7E72",
       256.54, 127.0,
       "Package_TO_SOT_SMD:SOT-23-5",
       "https://www.ti.com/lit/ds/symlink/tps7e72.pdf",
       "Texas Instruments", n_pins=5, ref_off=-10.16, val_off=-7.62)

# LNA passives ---------------------------------------------------------------
# C1 input DC block (horizontal, between RF_IN label and LNA RFIN)
add_passive("Device:C", "C1", "100pF", 80.01, 124.46, 90,
            "Capacitor_SMD:C_0402_1005Metric", "cap")
# R1 VBIAS bias resistor (horizontal, between VBIAS pin and +3V3)
add_passive("Device:R", "R1", "10k", 74.93, 127.0, 90,
            "Resistor_SMD:R_0402_1005Metric", "res")
# L1 bias choke (vertical, above LNA pin 7 RFOUT/VDD)
add_passive("Device:L", "L1", "56nH", 114.30, 120.65, 0,
            "Inductor_SMD:L_0402_1005Metric", "ind")
# C2 output DC block (horizontal, right of LNA pin 7)
add_passive("Device:C", "C2", "100pF", 125.73, 124.46, 90,
            "Capacitor_SMD:C_0402_1005Metric", "cap")
# C3 VDD bypass (vertical, between +3V3 rail and GND)
add_passive("Device:C", "C3", "100nF", 124.46, 115.57, 0,
            "Capacitor_SMD:C_0402_1005Metric", "cap")

# LDO passives ---------------------------------------------------------------
# C4 LDO input cap (vertical, left of LDO body)
add_passive("Device:C", "C4", "1uF", 241.30, 128.27, 0,
            "Capacitor_SMD:C_0402_1005Metric", "cap")
# C5 LDO output cap (vertical, right of LDO body)
add_passive("Device:C", "C5", "1uF", 271.78, 128.27, 0,
            "Capacitor_SMD:C_0402_1005Metric", "cap")

# Power symbols --------------------------------------------------------------
add_power("power:+3V3", "#PWR01", "+3V3", 71.12, 119.38)
add_power("power:+3V3", "#PWR02", "+3V3", 124.46, 109.22)

add_power("power:GND", "#PWR03", "GND", 100.33, 139.70)  # LNA EP
add_power("power:GND", "#PWR04", "GND", 124.46, 121.92)  # C3 bottom
add_power("power:GND", "#PWR05", "GND", 241.30, 134.62)  # C4 bottom (LDO input cap)
add_power("power:GND", "#PWR06", "GND", 256.54, 137.16)  # LDO pin 2 GND
add_power("power:GND", "#PWR07", "GND", 271.78, 134.62)  # C5 bottom (LDO output cap)

# Wires ----------------------------------------------------------------------
WIRES = [
    # LNA section
    # RF_IN label → C1 left
    ((66.04, 124.46), (76.20, 124.46)),
    # C1 right → LNA RFIN
    ((83.82, 124.46), (86.36, 124.46)),
    # R1 right → LNA VBIAS
    ((78.74, 127.0), (86.36, 127.0)),
    # R1 left → +3V3
    ((71.12, 127.0), (71.12, 119.38)),
    # LNA pin 7 → C2 left
    ((114.30, 124.46), (121.92, 124.46)),
    # L1 top → +3V3 rail
    ((114.30, 116.84), (114.30, 111.76)),
    # +3V3 rail horizontal (L1 to C3 area)
    ((114.30, 111.76), (124.46, 111.76)),
    # C3 top → +3V3 power symbol
    ((124.46, 111.76), (124.46, 109.22)),
    # C3 bottom → GND
    ((124.46, 119.38), (124.46, 121.92)),
    # ENABLE pin → right then up to rail
    ((114.30, 127.0), (119.38, 127.0)),
    ((119.38, 127.0), (119.38, 111.76)),
    # EP → GND
    ((100.33, 137.16), (100.33, 139.70)),

    # LNA → LDO main RF/IN net (broken at C4 pin endpoint for clarity)
    ((129.54, 124.46), (241.30, 124.46)),
    ((241.30, 124.46), (246.38, 124.46)),

    # LDO section
    # EN pin → IN pin (vertical tie at X = 246.38)
    ((246.38, 124.46), (246.38, 129.54)),
    # OUT → C5 top → VOUT label (passes through C5 top pin endpoint at 271.78)
    ((266.70, 124.46), (271.78, 124.46)),
    ((271.78, 124.46), (281.94, 124.46)),
    # C5 bottom → GND
    ((271.78, 132.08), (271.78, 134.62)),
    # C4 bottom → GND
    ((241.30, 132.08), (241.30, 134.62)),
    # LDO pin 2 GND → GND symbol
    ((256.54, 134.62), (256.54, 137.16)),
]

# Junctions (3-wire meets at NON-pin point) ----------------------------------
JUNCTIONS = [
    (119.38, 111.76),  # ENABLE wire tees into +3V3 rail
]

# Labels --------------------------------------------------------------------
# (text, x, y, angle, justify)
LABELS = [
    ("RF_IN", 66.04, 124.46, 0, "right"),
    ("LNA_RFOUT", 190.50, 124.46, 0, "left bottom"),
    ("VOUT", 281.94, 124.46, 0, "left"),
]

# No-connect markers ---------------------------------------------------------
NO_CONNECTS = [
    (86.36, 121.92),   # LNA pin 1
    (86.36, 129.54),   # LNA pin 4
    (114.30, 129.54),  # LNA pin 5
    (114.30, 121.92),  # LNA pin 8
    (266.70, 129.54),  # LDO pin 4 NC/ADJ
]

# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------

def emit_symbol(inst):
    out = []
    out.append(f'\t(symbol')
    out.append(f'\t\t(lib_id "{inst["lib_id"]}")')
    out.append(f'\t\t(at {inst["x"]} {inst["y"]} {inst["angle"]})')
    out.append(f'\t\t(unit 1) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)')
    out.append(f'\t\t(uuid {u()})')
    # Reference
    if inst.get("is_power"):
        # Hide reference for #PWR refdes
        out.append(f'\t\t(property "Reference" "{inst["ref"]}" (at {inst["x"]} {inst["y"]-6.35} 0) (effects (font (size 1.27 1.27)) (hide yes)))')
        # +3V3 label sits ABOVE the triangle (smaller y); GND label sits BELOW the triangle (larger y).
        if inst["lib_id"] == "power:+3V3":
            val_y = inst["y"] - 5.08
        else:  # power:GND
            val_y = inst["y"] + 5.08
        out.append(f'\t\t(property "Value" "{inst["value"]}" (at {inst["x"]} {val_y} 0) (effects (font (size 1.27 1.27))))')
    else:
        rx, ry = inst["ref_pos"]
        vx, vy = inst["val_pos"]
        out.append(f'\t\t(property "Reference" "{inst["ref"]}" (at {rx} {ry} 0) (effects (font (size 1.27 1.27))))')
        out.append(f'\t\t(property "Value" "{inst["value"]}" (at {vx} {vy} 0) (effects (font (size 1.27 1.27))))')
    out.append(f'\t\t(property "Footprint" "{inst["footprint"]}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')
    out.append(f'\t\t(property "Datasheet" "{inst["datasheet"]}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')
    if inst.get("manufacturer"):
        out.append(f'\t\t(property "Manufacturer" "{inst["manufacturer"]}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')
    for n in range(1, inst["n_pins"] + 1):
        out.append(f'\t\t(pin "{n}" (uuid {u()}))')
    out.append(f'\t\t(instances')
    out.append(f'\t\t\t(project "{PROJ}"')
    out.append(f'\t\t\t\t(path "/{SCH_UUID}" (reference "{inst["ref"]}") (unit 1))))')
    out.append(f'\t)')
    return "\n".join(out)


def emit_wire(p1, p2):
    return (f'\t(wire (pts (xy {p1[0]} {p1[1]}) (xy {p2[0]} {p2[1]}))\n'
            f'\t\t(stroke (width 0) (type default)) (uuid {u()}))')


def emit_junction(x, y):
    return f'\t(junction (at {x} {y}) (diameter 0) (color 0 0 0 0) (uuid {u()}))'


def emit_label(text, x, y, angle, justify):
    return (f'\t(label "{text}" (at {x} {y} {angle})\n'
            f'\t\t(effects (font (size 1.27 1.27)) (justify {justify}))\n'
            f'\t\t(uuid {u()}))')


def emit_no_connect(x, y):
    return f'\t(no_connect (at {x} {y}) (uuid {u()}))'


# ---------------------------------------------------------------------------
# Build .kicad_sch
# ---------------------------------------------------------------------------

lib_block = "\n\t\t".join([LNA_LIB, LDO_LIB, DEVICE_R, DEVICE_C, DEVICE_L, POWER_GND, POWER_3V3])

parts = []
parts.append('(kicad_sch')
parts.append('\t(version 20240618)')
parts.append('\t(generator "eeschema")')
parts.append('\t(generator_version "10.99")')
parts.append(f'\t(uuid {SCH_UUID})')
parts.append('\t(paper "A3")')
parts.append('\t(title_block')
parts.append('\t\t(title "LDO + LNA Demo")')
parts.append('\t\t(date "2026-05-22")')
parts.append('\t\t(rev "1")')
parts.append('\t\t(comment 1 "LNA RF_OUT wired to LDO VIN")')
parts.append('\t)')
parts.append('\t(lib_symbols')
parts.append(f'\t\t{lib_block}')
parts.append('\t)')

for w in WIRES:
    parts.append(emit_wire(*w))
for j in JUNCTIONS:
    parts.append(emit_junction(*j))
for nc in NO_CONNECTS:
    parts.append(emit_no_connect(*nc))
for lbl in LABELS:
    parts.append(emit_label(*lbl))
for inst in INSTANCES:
    parts.append(emit_symbol(inst))

parts.append(f'\t(sheet_instances (path "/" (page "1")))')
parts.append(')')

sch_text = "\n".join(parts) + "\n"
(ROOT / f"{PROJ}.kicad_sch").write_text(sch_text)

# .kicad_pro -----------------------------------------------------------------
pro = {
    "meta": {"filename": f"{PROJ}.kicad_pro", "version": 3},
    "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
    "sheets": [[SCH_UUID, ""]],
    "text_variables": {},
}
(ROOT / f"{PROJ}.kicad_pro").write_text(json.dumps(pro, indent=2))

print(f"wrote {ROOT / (PROJ + '.kicad_sch')}")
print(f"wrote {ROOT / (PROJ + '.kicad_pro')}")
