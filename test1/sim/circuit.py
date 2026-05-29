"""Parse a SPICE deck into a node-graph the GUI can draw.

The Simulation tab can render *what is actually being simulated* — the
behavioral SPICE model, not the full Altium schematic. The deck text is already
returned in the sim result; this module turns it into a structured
{elements, nets, subckts} graph so the frontend can lay it out as an interactive
diagram (elements = nodes, shared net names = edges).

This is a TOP-LEVEL parser: it reads the instance lines of the main circuit and
records `.subckt` *definitions* separately (so an `X` instance can be drawn as a
single block labelled with its subckt, with the internals available on demand).
It deliberately does NOT flatten subckts into the top level — the whole point of
the behavioral decks is that a part like the op-amp is ONE block, not its gm
guts.

What it understands (SPICE first-letter → terminal arity):
  R/L/C            2 nodes, then a value
  V/I              2 nodes, then a source spec (DC/AC/PWL/PULSE/expr)
  B                2 nodes, then a behavioral expr (V=… / I=…, may contain spaces)
  D                2 nodes, then a model
  M                4 nodes (D G S B), then a model        (level-1 MOSFET)
  Q                3 nodes (C B E),   then a model
  J                3 nodes,           then a model
  E/G/F/H          4 nodes (controlled sources), then gain/control
  X                N nodes + a subckt name (last token before PARAMS:/end)
Lines it skips: blank, `*` comments, and directives
(`.subckt`/`.ends`/`.model`/`.control`/`.endc`/`.end`/`.param`/…). A `* …`
comment immediately preceding an element becomes that element's `note` — the
deck builders write pinout hints there (e.g. "* --- Q40: D=… G=… S=… ---").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# First letter → number of TOP-LEVEL node terminals before the value/model.
# X is special (variable arity, ends with a subckt name) and handled separately.
_ARITY = {
    "R": 2, "L": 2, "C": 2,
    "V": 2, "I": 2, "B": 2,
    "D": 2,
    "M": 4, "E": 4, "G": 4, "F": 4, "H": 4,
    "Q": 3, "J": 3,
}

# Human label per first letter (for the diagram legend / node styling).
_KIND = {
    "R": "resistor", "L": "inductor", "C": "capacitor",
    "V": "vsource", "I": "isource", "B": "bsource",
    "D": "diode", "M": "mosfet", "Q": "bjt", "J": "jfet",
    "E": "vcvs", "G": "vccs", "F": "cccs", "H": "ccvs",
    "X": "subckt",
}

# Directive lines that are not circuit elements.
_DIRECTIVE = re.compile(r"^\.(subckt|ends|model|control|endc|end|param|include|lib|option|temp|ic|nodeset|global)\b",
                        re.IGNORECASE)

# Tokens in a V/I source spec that introduce the "value" (everything from here
# on is the source description, not nodes). Used to trim a clean display value.
_GND_NODES = {"0", "gnd", "gnd!"}


@dataclass
class Element:
    ref: str                     # SPICE deck ref, e.g. "RSENSE", "XOPA", "MQ40"
    kind: str                    # "resistor", "mosfet", "subckt", …
    nodes: list[str]             # net names this element connects to
    value: str = ""              # display value/expr/model ("5110", "PMOS_…", "V=…")
    subckt: str | None = None    # for X: the referenced subckt name
    note: str = ""               # preceding `* …` comment, if any
    refdes: str | None = None    # corresponding NETLIST refdes (R40, U41, …) or
    #                              None for behavioral scaffolding (ammeter, DUT
    #                              load, boundary source). Set by resolve_refdes.


@dataclass
class SubcktDef:
    name: str
    ports: list[str]
    params: dict[str, str] = field(default_factory=dict)
    body: list[str] = field(default_factory=list)   # raw interior lines (for drill-in)


@dataclass
class Circuit:
    elements: list[Element]
    nets: list[str]                                  # sorted unique top-level nets
    subckts: dict[str, SubcktDef]
    title: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "elements": [
                {"ref": e.ref, "kind": e.kind, "nodes": e.nodes,
                 "value": e.value, "subckt": e.subckt, "note": e.note,
                 "refdes": e.refdes}
                for e in self.elements
            ],
            "nets": self.nets,
            "subckts": {
                name: {"ports": s.ports, "params": s.params}
                for name, s in self.subckts.items()
            },
        }


def _split_params(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split a token list at a `PARAMS:` marker. Returns (pre, params) where
    `pre` is everything before PARAMS: and `params` is the parsed k=v map."""
    low = [t.lower() for t in tokens]
    if "params:" in low:
        i = low.index("params:")
        pre, rest = tokens[:i], tokens[i + 1:]
    else:
        pre, rest = tokens, []
    params: dict[str, str] = {}
    for tok in rest:
        if "=" in tok:
            k, v = tok.split("=", 1)
            params[k] = v
    return pre, params


def _clean_value(toks: list[str]) -> str:
    """A compact display string for a source/value tail."""
    return " ".join(toks).strip()


# A netlist-refdes-shaped token: 1-3 leading letters + digits (R40, U41, C13…).
_REFDES_SHAPE = re.compile(r"^[A-Za-z]{1,3}\d+$")


def _resolve_refdes(ref: str, refdes_map: dict[str, str | None] | None) -> str | None:
    """Map a SPICE deck element ref to its netlist refdes, in tiers:
      1. explicit per-deck map (XOPA→U41, MQ40→Q40, model-only→None),
      2. an R/L/C-prefixed element wrapping a refdes-shaped base (LC24→C24,
         RC24→C24, CC24→C24 — the PDN R-L-C cap model),
      3. the ref itself when it's already refdes-shaped (C10, R44, …),
      4. otherwise None (no schematic part).
    A map entry ALWAYS wins (including an explicit None for scaffolding)."""
    if refdes_map is not None and ref in refdes_map:
        return refdes_map[ref]
    # PDN L<ref>/R<ref>/C<ref> wrapping a refdes-shaped base (e.g. LC24 → C24)
    if len(ref) >= 2 and ref[0] in "LRC":
        base = ref[1:]
        if _REFDES_SHAPE.match(base):
            return base
    if _REFDES_SHAPE.match(ref):
        return ref
    return None


def parse_deck(deck: str, refdes_map: dict[str, str | None] | None = None) -> Circuit:
    """Parse a full SPICE deck into a Circuit graph. `refdes_map` (from the deck
    builder) maps SPICE element refs to netlist refdes; see _resolve_refdes."""
    raw_lines = deck.splitlines()

    # 1) Join continuation lines (a leading "+" continues the previous line).
    lines: list[str] = []
    for ln in raw_lines:
        if ln[:1] == "+" and lines:
            lines[-1] = lines[-1] + " " + ln[1:].strip()
        else:
            lines.append(ln)

    title = ""
    elements: list[Element] = []
    subckts: dict[str, SubcktDef] = {}
    nets: set[str] = set()

    pending_note = ""          # last `* …` comment seen at top level
    in_subckt: SubcktDef | None = None

    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            pending_note = ""
            continue

        # Title: a SPICE deck's first line is the title comment.
        if i == 0 and s.startswith("*"):
            title = s.lstrip("* ").strip()
            continue

        # Comment line: remember it (drives element labels) but don't emit.
        if s.startswith("*"):
            pending_note = s.lstrip("* ").strip()
            continue

        low = s.lower()

        # --- subckt definition boundaries -------------------------------
        if low.startswith(".subckt"):
            toks = s.split()
            name = toks[1] if len(toks) > 1 else "?"
            pre, params = _split_params(toks[2:])
            in_subckt = SubcktDef(name=name, ports=pre, params=params)
            subckts[name] = in_subckt
            pending_note = ""
            continue
        if low.startswith(".ends"):
            in_subckt = None
            pending_note = ""
            continue
        if in_subckt is not None:
            in_subckt.body.append(s)        # keep interior for drill-in
            continue

        # --- other directives (.model/.control/.tran/.dc/.end/…) --------
        if _DIRECTIVE.match(s) or low.startswith("."):
            # NB: control-block bodies (tran/dc/wrdata) sit between .control and
            # .endc; skip them too. We detect the block and drop until .endc.
            pending_note = ""
            continue

        # Inside a .control block? Drop until .endc. (We didn't track entry, so
        # detect common analysis verbs that only appear there.)
        if low.split()[0] in ("tran", "dc", "ac", "op", "wrdata", "print",
                               "plot", "let", "meas", "save", "run", "set"):
            pending_note = ""
            continue

        # --- a circuit element line -------------------------------------
        toks = s.split()
        ref = toks[0]
        first = ref[0].upper()
        rest = toks[1:]

        if first == "X":
            # X<name> n1 n2 ... <subcktname> [PARAMS: ...]
            pre, params = _split_params(rest)
            if pre:
                subckt_name = pre[-1]
                node_toks = pre[:-1]
            else:
                subckt_name, node_toks = None, []
            el = Element(ref=ref, kind="subckt", nodes=node_toks,
                         value=subckt_name or "", subckt=subckt_name,
                         note=pending_note)
        elif first in _ARITY:
            n = _ARITY[first]
            node_toks = rest[:n]
            value = _clean_value(rest[n:])
            el = Element(ref=ref, kind=_KIND.get(first, "element"),
                         nodes=node_toks, value=value, note=pending_note)
        else:
            # Unknown element letter — keep it but don't guess arity.
            el = Element(ref=ref, kind="element", nodes=[],
                         value=_clean_value(rest), note=pending_note)

        elements.append(el)
        for nd in el.nodes:
            nets.add(nd)
        pending_note = ""

    # resolve each element's netlist refdes
    for e in elements:
        e.refdes = _resolve_refdes(e.ref, refdes_map)

    return Circuit(
        elements=elements,
        nets=sorted(nets, key=lambda x: (x in _GND_NODES, x.lower())),
        subckts=subckts,
        title=title,
    )


def circuit_dict(deck: str | None,
                 refdes_map: dict[str, str | None] | None = None) -> dict | None:
    """Convenience: parse a deck (or None) to a JSON-able dict (or None).
    `refdes_map` ties model elements back to netlist refdes (see parse_deck)."""
    if not deck:
        return None
    try:
        return parse_deck(deck, refdes_map).to_dict()
    except Exception:
        # Parsing must never break the sim result; degrade to "no graph".
        return None


# --- self-test --------------------------------------------------------------
# No pytest in this repo; run `python -m test1.sim.circuit` to smoke-test the
# parser against every implemented deck (asserts arity/structure invariants).
if __name__ == "__main__":      # pragma: no cover
    import os
    os.environ.setdefault("PYTHONUTF8", "1")

    # Hand-crafted unit checks (independent of ngspice) -------------------
    SAMPLE = """* sample title
.subckt OPA OUT INP INN VCC VEE PARAMS: AOL=3e6 VOS=15e-6
BGM 0 INT I = 1e-3*(V(INP)-V(INN)+{VOS})
ROUT OUTB OUT 50
.ends OPA
.model PMOS_X PMOS (VTO=-0.7)
RSENSE VSENSE V3V3 5110
XOPA OPAOUT VDAC VSENSE V3V3 0 OPA PARAMS: VOS=5e-06
MQ40 BIASD OPAOUT VSENSE V3V3 PMOS_X
BLOAD VDDIO 0 I=0.05 + 0.20*u(time-0.2m)
.control
tran 20n 0.4m
wrdata x.dat v(vddio)
.endc
.end
"""
    c = parse_deck(SAMPLE)
    assert c.title == "sample title", c.title
    assert list(c.subckts) == ["OPA"], list(c.subckts)
    assert c.subckts["OPA"].ports == ["OUT", "INP", "INN", "VCC", "VEE"]
    refs = {e.ref: e for e in c.elements}
    assert set(refs) == {"RSENSE", "XOPA", "MQ40", "BLOAD"}, set(refs)
    assert refs["RSENSE"].nodes == ["VSENSE", "V3V3"] and refs["RSENSE"].value == "5110"
    assert refs["XOPA"].subckt == "OPA"
    assert refs["XOPA"].nodes == ["OPAOUT", "VDAC", "VSENSE", "V3V3", "0"]
    assert refs["MQ40"].nodes == ["BIASD", "OPAOUT", "VSENSE", "V3V3"]   # 4-term
    assert refs["MQ40"].value == "PMOS_X"
    # Behavioral source: nodes are ONLY the two terminals; the spaced expr is value.
    assert refs["BLOAD"].nodes == ["VDDIO", "0"], refs["BLOAD"].nodes
    assert refs["BLOAD"].value.startswith("I=0.05"), refs["BLOAD"].value
    # No control-block verbs leaked in as elements.
    assert not any(e.ref.lower() in ("tran", "wrdata", "dc") for e in c.elements)

    # refdes resolution: explicit map wins; refdes-shaped default; None for the
    # rest; and the L/R/C<ref> pattern (PDN cap model).
    c2 = parse_deck(SAMPLE, {"XOPA": "U41", "MQ40": "Q40", "BLOAD": None})
    r2 = {e.ref: e.refdes for e in c2.elements}
    assert r2["XOPA"] == "U41", r2            # explicit map (mangled name → refdes)
    assert r2["MQ40"] == "Q40", r2            # explicit map wins over self-default
    assert r2["BLOAD"] is None, r2            # explicit model-only
    assert r2["RSENSE"] is None, r2           # not refdes-shaped, no map → None
    pat = parse_deck("* t\nLC24 A C24_a 1n\nRC24 C24_a C24_b 1\nCC24 C24_b 0 1u\nC13 X 0 1u\n.end")
    pr = {e.ref: e.refdes for e in pat.elements}
    assert pr["LC24"] == "C24" and pr["RC24"] == "C24" and pr["CC24"] == "C24", pr
    assert pr["C13"] == "C13", pr             # refdes-shaped default
    print("unit checks: OK")

    # Live checks against the real decks (needs ngspice for service) ------
    try:
        from . import service
    except Exception:
        from test1.sim import service     # when run as a script
    combos = [("opa_bias", "dc_sweep"), ("ldo_rail", "transient_powerup"),
              ("vddio_pdn", "transient_load_step"), ("vddd_pdn", "transient_load_step")]
    for blk, st in combos:
        res = service.run_block_sim(blk, st)
        deck = res.get("deck")
        if not deck:
            print(f"{blk}/{st}: status={res.get('status')} (no deck — skipped)")
            continue
        cc = parse_deck(deck)
        assert cc.elements, f"{blk}/{st}: no elements parsed"
        # Every element's nodes must be a subset of the net set.
        for e in cc.elements:
            for nd in e.nodes:
                assert nd in cc.nets, f"{blk}/{st}: {e.ref} node {nd} not in nets"
        # Every X instance must resolve to a known subckt.
        for e in cc.elements:
            if e.kind == "subckt":
                assert e.subckt in cc.subckts, f"{blk}/{st}: {e.ref}->{e.subckt} undefined"
        print(f"{blk}/{st}: {len(cc.elements)} elements, {len(cc.nets)} nets, "
              f"subckts={list(cc.subckts)}  OK")
    print("live checks: OK")
