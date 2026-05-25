"""Project-wide constants and identifier helpers.

Holds: file paths, KiCad file-format constants, the deterministic-UUID
namespace + `uid()` helper, sheet name/uuid/page tables, the FMC LA-bank
pin-assignment table, and the per-block footprint shortcuts.

Everything in this module is data + pure helpers — no I/O, no Sheet, no
emit. Sheet builders pull what they need via `from .config import …`.
"""

from __future__ import annotations

import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths & file-format constants
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent.parent
PARTS_LIB = PROJECT_DIR / "Parts Library"
OUT_DIR = PROJECT_DIR / "kicad"
RENDER_DIR = OUT_DIR / "render"
PROJECT_NAME = "test1"

# Dev-build file-format triple — see feedback_kicad_generator_lessons.md
# §"File-format constants". Wrong values silently break load on this build.
SCH_VERSION = "20250114"
GENERATOR = "eeschema"
GENERATOR_VERSION = "10.99"

KICAD_CLI = "/Users/masonking/Downloads/kicad/build/kicad/KiCad.app/Contents/MacOS/kicad-cli"


# ---------------------------------------------------------------------------
# Deterministic UUID generation
# ---------------------------------------------------------------------------

_NS = uuid.UUID("11111111-2222-3333-4444-555555555555")


def uid(name: str) -> str:
    """Deterministic uuid5 from the project namespace + name string.

    Same name → same UUID across runs, so emitted files diff cleanly.
    """
    return str(uuid.uuid5(_NS, name))


# ---------------------------------------------------------------------------
# Sheet identifiers
# ---------------------------------------------------------------------------

ROOT_UUID = uid("root")
SHEET_NAMES = ["fmc", "power", "bobcat", "eeprom", "bias", "connectors"]
SHEET_UUIDS = {name: uid(f"sheet_{name}") for name in SHEET_NAMES}
SHEET_TITLES = {
    "fmc": "FMC Connector",
    "power": "Power",
    "bobcat": "Bobcat DUT",
    "eeprom": "EEPROM",
    "bias": "Bias Generators",
    "connectors": "Connectors / Breakouts",
}

# Page numbers: root=1, children in declared order
PAGE_NUMBERS: dict[str, str] = {"root": "1"}
for _i, _n in enumerate(SHEET_NAMES, start=2):
    PAGE_NUMBERS[_n] = str(_i)


# ---------------------------------------------------------------------------
# FMC LA-bank pin assignments
# ---------------------------------------------------------------------------
# Sequential assignment from LA00..LA27 (P pin of each pair, single-ended use).
# Cross-reference design_requirements.md FMC LA-pair table for the pin-to-LA
# mapping. Each entry: net_name -> (row_letter, pin_number).
LA_ASSIGN: dict[str, tuple[str, int]] = {
    # E1 — Bobcat ↔ FMC SPI / sample-out routing (via 0Ω on FMC sheet)
    "SAMPLE_OUTV":   ("H",  6),   # LA00_CC
    "SAMPLE_OUT0":   ("C",  8),   # LA01_CC
    "SAMPLE_OUT1":   ("G",  7),   # LA02
    "SAMPLE_OUT2":   ("H",  9),   # LA03
    "SAMPLE_OUT3":   ("G", 10),   # LA04
    "SAMPLE_OUT4":   ("C", 11),   # LA05
    "SAMPLE_OUT5":   ("D", 10),   # LA06
    "SAMPLE_OUT6":   ("G", 13),   # LA07
    "SAMPLE_OUT7":   ("H", 12),   # LA08
    "CS_L":          ("C", 14),   # LA09
    "SCLK":          ("D", 14),   # LA10
    "MOSI":          ("G", 16),   # LA11
    "MISO":          ("H", 15),   # LA12
    "SPI_DMODE":     ("C", 17),   # LA13
    "RESET_N":       ("D", 18),   # LA14
    # E2 — OSC_EN / WEIGHT_EN / SAMPLE_TRIG (also SMA-routable on connectors)
    "OSC_EN":        ("G", 19),   # LA15
    "WEIGHT_EN":     ("H", 18),   # LA16
    "SAMPLE_TRIG":   ("C", 20),   # LA17_CC
    # W1 — Power EN signals from FPGA
    "LDO_EN":        ("D", 22),   # LA18_CC
    "LSW_EN":        ("G", 22),   # LA19
    # E7 — Bias isolation FET enables (gates Q42/Q43 when populated)
    "BIAS_ISO0":     ("H", 21),   # LA20
    "BIAS_ISO1":     ("G", 25),   # LA21
    # E5 — TPS7A8401A ANY-OUT setpoint pins
    "LDO_SET_50mV":  ("H", 24),   # LA22
    "LDO_SET_100mV": ("C", 23),   # LA23
    "LDO_SET_200mV": ("G", 28),   # LA24
    "LDO_SET_400mV": ("H", 27),   # LA25
    "LDO_SET_800mV": ("C", 26),   # LA26
    "LDO_SET_1V6":   ("D", 26),   # LA27
}


# ---------------------------------------------------------------------------
# Common footprint constants
# ---------------------------------------------------------------------------

FP_R0402 = "Resistor_SMD:R_0402_1005Metric"
FP_C0402 = "Capacitor_SMD:C_0402_1005Metric"
FP_C0603 = "Capacitor_SMD:C_0603_1608Metric"
FP_C0805 = "Capacitor_SMD:C_0805_2012Metric"
FP_SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
FP_VQFN20 = "Package_DFN_QFN:VQFN-20-1EP_3.5x3.5mm_P0.5mm_EP1.6x1.6mm"
FP_QFN10 = "Package_DFN_QFN:VQFN-10-1EP_3x3mm_P0.5mm_EP1.6x1.6mm"
FP_PMOS_DFN = "Package_DFN_QFN:DFN-3-1EP_1.0x1.0mm_P0.65mm_EP0.5x0.5mm"
FP_SOT23 = "Package_TO_SOT_SMD:SOT-23"
FP_WCSP4 = "Package_DirectFETandLGA:Texas_DSBGA-4_0.6x1.0mm_Layout2x2_P0.4mm"
FP_QFN40 = "Bobcat:QFN-40_5x5mm_P0.4mm_EP3.5mm"
FP_SMA = "Connector_Coaxial:SMA_Amphenol_HRM-G_Vertical"
FP_HEADER_1x2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
FP_HEADER_1x4 = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
FP_TESTPOINT = "TestPoint:TestPoint_THTPad_D5.0mm_Drill3.0mm"
FP_FMC = "Connector:FMC_LPC_ASP-134606-01"
