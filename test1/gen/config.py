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
# Each entry: net_name -> (row_letter, pin_number) = the P pin of LA<nn> at its
# ACTUAL VITA 57.1 LPC connector position.
#   Authoritative pinout: fmchub.github.io/appendix/
#     VITA57_FMC_HPC_LPC_SIGNALS_AND_PINOUT.html (LPC table, rows C/D/G/H).
# NOTE (2026-05-27): a prior version of this table (and the design_requirements
# FMC table) had rows C<->D and G<->H TRANSPOSED — a mirrored/bottom-view read of
# the connector. VITA 57.1 pin NAMES mate 1:1 (mezzanine Cn <-> carrier Cn); the
# footprint handles the physical mirror, NOT the netlist. The values below are
# the un-swapped, correct LA_P positions; cross-checked pin-by-pin vs the spec.
LA_ASSIGN: dict[str, tuple[str, int]] = {
    # E1 — Bobcat ↔ FMC SPI / sample-out routing (via 0Ω on FMC sheet)
    "SAMPLE_OUTV":   ("G",  6),   # LA00_P_CC
    "SAMPLE_OUT0":   ("D",  8),   # LA01_P_CC
    "SAMPLE_OUT1":   ("H",  7),   # LA02_P
    "SAMPLE_OUT2":   ("G",  9),   # LA03_P
    "SAMPLE_OUT3":   ("H", 10),   # LA04_P
    "SAMPLE_OUT4":   ("D", 11),   # LA05_P
    "SAMPLE_OUT5":   ("C", 10),   # LA06_P
    "SAMPLE_OUT6":   ("H", 13),   # LA07_P
    "SAMPLE_OUT7":   ("G", 12),   # LA08_P
    "CS_L":          ("D", 14),   # LA09_P
    "SCLK":          ("C", 14),   # LA10_P
    "MOSI":          ("H", 16),   # LA11_P
    "MISO":          ("G", 15),   # LA12_P
    "SPI_DMODE":     ("D", 17),   # LA13_P
    "RESET_N":       ("C", 18),   # LA14_P
    # E2 — OSC_EN / WEIGHT_EN / SAMPLE_TRIG (also SMA-routable on connectors)
    "OSC_EN":        ("H", 19),   # LA15_P
    "WEIGHT_EN":     ("G", 18),   # LA16_P
    "SAMPLE_TRIG":   ("D", 20),   # LA17_P_CC
    # W1 — Power EN signals from FPGA
    "LDO_EN":        ("C", 22),   # LA18_P_CC
    "LSW_EN":        ("H", 22),   # LA19_P
    # BIAS_ISO0/1 (LA20_P G21 / LA21_P H25) removed — bias isolation FETs were
    # dropped to match the deck's backup topology; those LA pins are now unused.
    # E5 — TPS7A8401A ANY-OUT setpoint pins
    "LDO_SET_25mV":  ("G", 24),   # LA22_P
    "LDO_SET_50mV": ("D", 23),   # LA23_P
    "LDO_SET_100mV": ("H", 28),   # LA24_P
    "LDO_SET_200mV": ("G", 27),   # LA25_P
    "LDO_SET_400mV": ("D", 26),   # LA26_P
    "LDO_SET_800mV":   ("C", 26),   # LA27_P
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
