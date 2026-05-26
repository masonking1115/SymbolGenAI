"""Phase 4: autofix proposer + approval-gated applier.

For each Finding whose `autofix` category is one of:
  - "nc_marker"
  - "decoupling"
  - "pullup_pulldown"

…this module produces a concrete proposed edit (file + diff snippet)
and either applies it directly (trivial fixes) or surfaces it for user
approval first.

Trivial vs non-trivial
----------------------
"Trivial" here means: the edit has no judgment calls — the value, the
target net, and the receiving file are all unambiguous from the
Finding's `autofix_data` payload. Currently:

  - `nc_marker`: trivial. Adds (no_connect …) — purely additive.
  - `pullup_pulldown`: trivial. The Finding names net + rail + kind;
    the new resistor gets the next free RNN.
  - `decoupling`: trivial as a YAML edit (next free CNN), but the
    layout placement (x, y in build_<sheet>.py) is a judgment call.
    For now we add the YAML entry + a TODO comment in build_*.py
    naming the cap, so the build fails until the user places it.

Editing strategy
----------------
We append to netlist/<sheet>.yaml (text-level append, preserves
comments). build_<sheet>.py gets a `# TODO(autofix): place …` line
near the top so the user knows what's pending.

NOTE on side effects:
  Applying any autofix breaks the build until the user places the
  new part in the corresponding build_<sheet>.py — the strict
  validator gates on this. That's intentional: the user gets a clear
  "you still need to wire it" signal rather than a silent partial fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .findings import Finding

PROJECT_DIR = Path(__file__).resolve().parent.parent
NETLIST_DIR = PROJECT_DIR / "netlist"
BUILDER_DIR = PROJECT_DIR / "gen"


@dataclass
class Proposal:
    finding: Finding
    summary: str               # one-line description of what will happen
    file_edits: list[tuple[Path, str]]   # [(path, new content), ...] preview
    notes: list[str]           # extra notes for the user (next steps)


# ---------------------------------------------------------------------------
# Refdes allocator — scans the netlist YAMLs to find the next free letter+N.
# ---------------------------------------------------------------------------

_REFDES_LINE = re.compile(r"^\s\s([RCQUDLJ][\w]*):", re.MULTILINE)


def _next_free_refdes(prefix: str, sheet: str | None = None) -> str:
    """Return the next free refdes with the given letter prefix.

    KiCad refdes namespace is GLOBAL across sheets — so we scan every YAML
    and pick the next integer that isn't taken anywhere. `sheet` is
    advisory: if given, we look for a free number in the local decade
    range that the sheet already uses (R20-29 for bobcat, etc.) so new
    refdes cluster with existing ones.
    """
    used: set[int] = set()
    for yml in NETLIST_DIR.glob("*.yaml"):
        text = yml.read_text()
        for m in _REFDES_LINE.finditer(text):
            tok = m.group(1)
            mn = re.match(rf"^{prefix}(\d+)$", tok)
            if mn:
                used.add(int(mn.group(1)))
    if not used:
        return f"{prefix}1"

    # If sheet hint given, try to allocate within its existing decade.
    if sheet:
        sheet_text = (NETLIST_DIR / f"{sheet}.yaml").read_text() \
            if (NETLIST_DIR / f"{sheet}.yaml").exists() else ""
        sheet_used: set[int] = set()
        for m in _REFDES_LINE.finditer(sheet_text):
            tok = m.group(1)
            mn = re.match(rf"^{prefix}(\d+)$", tok)
            if mn:
                sheet_used.add(int(mn.group(1)))
        if sheet_used:
            base = (min(sheet_used) // 10) * 10
            for n in range(base, base + 10):
                if n not in used:
                    return f"{prefix}{n}"

    return f"{prefix}{max(used) + 1}"


# ---------------------------------------------------------------------------
# YAML text-level editor (no parse-and-rewrite — preserves comments).
# ---------------------------------------------------------------------------

def _append_part_block(yaml_text: str, refdes: str, value: str,
                       footprint: str, notes: str) -> str:
    """Insert a new part entry just before the `nets:` section."""
    new_entry = (
        f"  {refdes}: {{ lib_id: Device:{refdes[0]}, value: \"{value}\", "
        f"footprint: {footprint}, notes: \"{notes}\" }}\n"
    )
    nets_pos = yaml_text.find("\nnets:")
    if nets_pos == -1:
        return yaml_text.rstrip() + "\n" + new_entry
    return yaml_text[:nets_pos] + "\n" + new_entry + yaml_text[nets_pos:]


def _append_net_member(yaml_text: str, net_name: str, member: str) -> str:
    """Add `member` to the named net's member list. Handles inline-list
    (`members: [a, b]`) and block-list (`members:\\n  - a\\n  - b`) styles."""
    inline = re.search(
        rf"({re.escape(net_name)}:[^\n]*members:\s*)\[([^\]]*)\]",
        yaml_text,
    )
    if inline:
        existing = inline.group(2).strip()
        if existing:
            new_list = existing.rstrip(",") + f", {member}"
        else:
            new_list = member
        return (yaml_text[:inline.start(2)] + new_list
                + yaml_text[inline.end(2):])

    block = re.search(
        rf"({re.escape(net_name)}:[\s\S]*?members:\s*\n)((?:\s+-\s+[^\n]+\n)+)",
        yaml_text,
    )
    if block:
        insert_at = block.end(2)
        indent = "      "  # match the existing 6-space bullet indent
        return (yaml_text[:insert_at]
                + f"{indent}- {member}\n"
                + yaml_text[insert_at:])

    # Net doesn't exist yet — create it. Use the trailing newline before EOF.
    return yaml_text.rstrip() + (
        f"\n  {net_name}:\n    type: power\n    members: [{member}]\n"
    )


# ---------------------------------------------------------------------------
# Per-category proposal builders
# ---------------------------------------------------------------------------

def _propose_pullup_pulldown(f: Finding) -> Proposal:
    sheet = f.sheet
    yaml_path = NETLIST_DIR / f"{sheet}.yaml"
    text = yaml_path.read_text()
    refdes = _next_free_refdes("R", sheet)
    data = f.autofix_data
    net = data.get("net", "")
    rail = data.get("rail", "")
    value = data.get("value", "10k")
    kind = data.get("kind", "pull")
    notes = f"autofix: {kind} on {net} → {rail}"
    text2 = _append_part_block(text, refdes, value,
                                "Resistor_SMD:R_0402_1005Metric", notes)
    text2 = _append_net_member(text2, net, f"{refdes}.1")
    text2 = _append_net_member(text2, rail, f"{refdes}.2")
    return Proposal(
        finding=f,
        summary=f"Add {refdes} = {value} between {net} and {rail} on {sheet}",
        file_edits=[(yaml_path, text2)],
        notes=[
            f"Place {refdes} near the net's existing entry in "
            f"gen/build_{sheet}.py before re-running gen_schematic.py — "
            f"the validator will fail until {refdes} is laid out.",
        ],
    )


def _propose_decoupling(f: Finding) -> Proposal:
    sheet = f.sheet
    yaml_path = NETLIST_DIR / f"{sheet}.yaml"
    text = yaml_path.read_text()
    refdes = _next_free_refdes("C", sheet)
    data = f.autofix_data
    value = data.get("value", "0.1uF")
    rail_label = data.get("rail_label", "")
    # Pick the most-likely net to attach to: prefer +VDDIO-style (named rail)
    # over internal_<rail>_path so the cap shows up alongside others on the rail.
    nets = data.get("nets", [])
    rail_net = next((n for n in nets if n.startswith("+")), None) \
        or (nets[0] if nets else "GND")
    notes = f"autofix: decoupling on {rail_label}"
    text2 = _append_part_block(text, refdes, value,
                                "Capacitor_SMD:C_0402_1005Metric", notes)
    text2 = _append_net_member(text2, rail_net, f"{refdes}.1")
    text2 = _append_net_member(text2, "GND", f"{refdes}.2")
    return Proposal(
        finding=f,
        summary=f"Add {refdes} = {value} on {rail_net}/GND ({sheet})",
        file_edits=[(yaml_path, text2)],
        notes=[
            f"Place {refdes} near {f.component_refs[0] if f.component_refs else 'the IC'} "
            f"in gen/build_{sheet}.py — recommend placement in the same "
            f"cluster as existing {rail_net} caps.",
        ],
    )


def _propose_nc_marker(f: Finding) -> Proposal:
    # The build_*.py is where no_connect markers are actually emitted, so
    # the proposal is a code suggestion rather than a YAML edit. We surface
    # the suggestion as text — applying it cleanly requires reading the
    # builder structure. For now we just propose; we don't auto-edit code.
    return Proposal(
        finding=f,
        summary=f"Add no_connect on {f.subject} (manual code edit)",
        file_edits=[],
        notes=[
            f"In gen/build_{f.sheet}.py, find the cluster where "
            f"{f.component_refs[0] if f.component_refs else f.subject} is placed "
            f"and add `s.add(no_connect(<pin x>, <pin y>))` for {f.subject}.",
        ],
    )


_PROPOSERS = {
    "pullup_pulldown": _propose_pullup_pulldown,
    "decoupling":      _propose_decoupling,
    "nc_marker":       _propose_nc_marker,
}


def propose(f: Finding) -> Proposal | None:
    fn = _PROPOSERS.get(f.autofix)
    return fn(f) if fn else None


# ---------------------------------------------------------------------------
# Dispatcher — prompts the user per proposal and applies on yes.
# ---------------------------------------------------------------------------

def _apply(proposal: Proposal) -> None:
    for path, new_text in proposal.file_edits:
        path.write_text(new_text)
        print(f"    edited {path.relative_to(PROJECT_DIR.parent)}")
    for note in proposal.notes:
        print(f"    next: {note}")


def run(findings: list[Finding], *,
        non_interactive: bool = False,
        apply_trivial: bool = False) -> None:
    """Walk findings, propose fixes, apply with approval.

    Args:
      non_interactive: if True, never prompt; emit proposals to stdout only.
      apply_trivial:   if True, auto-apply pullup_pulldown + decoupling
                       proposals without asking; nc_marker still prints
                       (it's a code edit, not a YAML edit).
    """
    proposals: list[Proposal] = []
    manual: list[Finding] = []
    for f in findings:
        prop = propose(f)
        if prop is None:
            manual.append(f)
        else:
            proposals.append(prop)

    if not proposals and not manual:
        print("Phase 4: no findings to fix.")
        return

    print(f"Phase 4: {len(proposals)} autofix proposal(s), "
          f"{len(manual)} manual finding(s)")
    print()

    for i, prop in enumerate(proposals, start=1):
        f = prop.finding
        print(f"--- proposal {i}/{len(proposals)} — {f.severity.value} ---")
        print(f"  finding: {f.title}")
        print(f"  category: {f.autofix}")
        print(f"  proposed: {prop.summary}")
        for path, _ in prop.file_edits:
            print(f"    file: {path.relative_to(PROJECT_DIR.parent)}")
        for n in prop.notes:
            print(f"    note: {n}")

        if apply_trivial and f.autofix in ("pullup_pulldown", "decoupling"):
            print("  → auto-applying (trivial bucket)")
            _apply(prop)
            print()
            continue

        if non_interactive:
            print("  (non-interactive — skipping)")
            print()
            continue

        ans = input("  apply? [y/N] ").strip().lower()
        if ans == "y":
            _apply(prop)
        else:
            print("  skipped.")
        print()

    if manual:
        print(f"--- {len(manual)} manual finding(s) — fix instructions ---")
        for f in manual:
            print(f"  · {f.severity.value} {f.rule_id} ({f.subject})")
            print(f"      {f.fix}")
        print()
        print("Manual fixes are listed above — these require human judgment.")
        print("Edit gen/build_<sheet>.py or netlist/<sheet>.yaml as needed,")
        print("then re-run `python3 run_review.py` to confirm the finding "
              "is closed.")
