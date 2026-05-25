"""Phase 2 prep: build/load a JSON fingerprint for each MPN.

The fingerprint is a cache extracted from each part's datasheet PDF. It
sits at `parts/<MPN>.json` (gitignored — derived, not source). On the
first run it's empty; the LLM reviewer populates it as it touches each
part. Subsequent runs read JSON instead of re-parsing the PDF.

Schema (kept narrow on purpose — only fields the reviewer asks about):

    {
      "mpn": "TPS7A8401A",
      "package": "VQFN-20-1EP",
      "abs_max": {"Vin": "7 V", "Iout": "3 A", ...},
      "pinout": {
        "1":  {"name": "OUT",    "type": "power_out"},
        "2":  {"name": "SNS",    "type": "analog_in"},
        ...
        "21": {"name": "EP",     "type": "ground"}
      },
      "open_drain_outputs": ["PG"],     // pin names
      "nc_pins": [],                     // pins datasheet calls out as NC
      "decoupling": {
        "Vin": [{"value": "10uF", "context": "bulk"},
                {"value": "0.1uF","context": "HF"}],
        "BIAS": [{"value": "1uF", "context": "noise reference"}]
      },
      "strap_pins": {                    // mode/config pins
        "ANY-OUT": "FPGA-driven setpoint (50/100/200/400/800 mV + 1.6 V binary)"
      },
      "notes": "Free-form notes the reviewer wants persisted."
    }

The reviewer can ALSO write a fingerprint for a part it hasn't seen,
so this file just defines the schema + helpers — it does not extract
any fingerprints itself. Extraction is the Explore subagent's job
(driven from semantic_review.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PARTS_DIR = Path(__file__).resolve().parent.parent / "parts"


@dataclass
class Fingerprint:
    mpn: str
    package: str = ""
    abs_max: dict[str, str] = field(default_factory=dict)
    pinout: dict[str, dict] = field(default_factory=dict)
    open_drain_outputs: list[str] = field(default_factory=list)
    nc_pins: list[str] = field(default_factory=list)
    decoupling: dict[str, list[dict]] = field(default_factory=dict)
    strap_pins: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "mpn": self.mpn,
            "package": self.package,
            "abs_max": self.abs_max,
            "pinout": self.pinout,
            "open_drain_outputs": self.open_drain_outputs,
            "nc_pins": self.nc_pins,
            "decoupling": self.decoupling,
            "strap_pins": self.strap_pins,
            "notes": self.notes,
        }


def path_for(mpn: str) -> Path:
    return PARTS_DIR / f"{mpn}.json"


def load(mpn: str) -> Fingerprint | None:
    p = path_for(mpn)
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return Fingerprint(
        mpn=d.get("mpn", mpn),
        package=d.get("package", ""),
        abs_max=d.get("abs_max", {}),
        pinout=d.get("pinout", {}),
        open_drain_outputs=d.get("open_drain_outputs", []),
        nc_pins=d.get("nc_pins", []),
        decoupling=d.get("decoupling", {}),
        strap_pins=d.get("strap_pins", {}),
        notes=d.get("notes", ""),
    )


def save(fp: Fingerprint) -> Path:
    PARTS_DIR.mkdir(parents=True, exist_ok=True)
    p = path_for(fp.mpn)
    p.write_text(json.dumps(fp.to_dict(), indent=2))
    return p


def datasheet_paths(mpn: str) -> list[Path]:
    """Return any PDFs sitting under Parts Library/<MPN>/."""
    parts_lib = Path(__file__).resolve().parent.parent / "Parts Library"
    candidates: list[Path] = []
    for d in parts_lib.iterdir():
        if not d.is_dir():
            continue
        if mpn.lower() in d.name.lower() or d.name.lower() in mpn.lower():
            candidates.extend(d.glob("*.pdf"))
    return candidates
