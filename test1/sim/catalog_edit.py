"""Surgical, comment-preserving edits to blocks.yaml.

The catalog carries load-bearing curation comments (the boundary-vs-extracted
header, per-block reviewer notes), so we MUST NOT round-trip it through
yaml.safe_load/dump (that strips comments). Instead we edit the specific lines
for a sim_type's `pass:` criterion and a block's boundary `params`, then VALIDATE
by re-parsing the whole file and confirming the target still resolves — writing
only if it's still valid (otherwise raise, no write). Plain regex, no extra deps.

Editable surface (per the GUI "edit requirements" feature):
  - a sim_type's `pass:` string  (the acceptance criterion)
  - a sim_type's `rationale:` string
  - a boundary net's param value  (operating point / load / limit)
  - add a new param to a boundary net
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .catalog import CATALOG_PATH


class CatalogEditError(ValueError):
    """Raised when an edit would not apply cleanly or would break the YAML."""


# ---- low-level: locate a block / sim_type section by line range -------------

def _lines() -> list[str]:
    return CATALOG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)


def _block_range(lines: list[str], block_id: str) -> tuple[int, int]:
    """[start, end) line indices of the `- id: <block>` list item."""
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^\s*-\s*id:\s*{re.escape(block_id)}\s*$", ln):
            start = i
            break
    if start is None:
        raise CatalogEditError(f"block {block_id!r} not found in catalog")
    # the block ends at the next top-level "  - id:" (2-space indent list item)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s{2}-\s+id:\s", lines[j]):
            end = j
            break
    return start, end


def _sim_range(lines: list[str], lo: int, hi: int, sim_type: str) -> tuple[int, int]:
    """[start, end) of a `- type: <sim>` entry within a block's line range."""
    start = None
    for i in range(lo, hi):
        if re.match(rf"^\s*-\s*type:\s*{re.escape(sim_type)}\s*$", lines[i]):
            start = i
            break
    if start is None:
        raise CatalogEditError(f"{sim_type!r} not found in block")
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = hi
    for j in range(start + 1, hi):
        s = lines[j]
        if s.strip() and (len(s) - len(s.lstrip())) <= indent and s.lstrip().startswith("- "):
            end = j
            break
        # also stop at a sibling block-level key (e.g. notes:/boundaries:) at a
        # shallower indent than the list item
        if s.strip() and (len(s) - len(s.lstrip())) < indent:
            end = j
            break
    return start, end


# ---- validation: re-parse + confirm the target still resolves --------------

def _validate_and_write(new_text: str, block_id: str, sim_type: str | None) -> None:
    try:
        data = yaml.safe_load(new_text)
    except yaml.YAMLError as e:
        raise CatalogEditError(f"edit produced invalid YAML: {e}") from e
    blocks = (data or {}).get("blocks", [])
    blk = next((b for b in blocks if b.get("id") == block_id), None)
    if blk is None:
        raise CatalogEditError("edit lost the target block — aborted")
    if sim_type is not None:
        if not any(s.get("type") == sim_type for s in blk.get("sim_types", [])):
            raise CatalogEditError("edit lost the target sim type — aborted")
    CATALOG_PATH.write_text(new_text, encoding="utf-8")


# ---- public edits ----------------------------------------------------------

def _yaml_quote(s: str) -> str:
    """Double-quote a scalar for YAML, escaping quotes/backslashes."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_sim_field(block_id: str, sim_type: str, field: str, value: str) -> None:
    """Set a sim_type's `pass:` or `rationale:` to a new string."""
    if field not in ("pass", "rationale"):
        raise CatalogEditError(f"field {field!r} not editable")
    lines = _lines()
    lo, hi = _block_range(lines, block_id)
    s0, s1 = _sim_range(lines, lo, hi, sim_type)
    # find the field line within the sim entry; support `field: "..."` and
    # block scalars `field: >` (rationale) — for the latter we replace the whole
    # folded block with a single quoted line.
    field_re = re.compile(rf"^(\s*){field}:\s*(.*)$")
    idx = None
    indent = ""
    for i in range(s0, s1):
        m = field_re.match(lines[i])
        if m:
            idx = i
            indent = m.group(1)
            rest = m.group(2).strip()
            break
    new_line = f"{indent}{field}: {_yaml_quote(value)}\n"
    if idx is None:
        # field absent → insert right after the `- type:` line
        lines.insert(s0 + 1, new_line)
    else:
        # if it was a folded/literal block ( > or | ), drop its continuation lines
        end = idx + 1
        if rest in (">", "|", ">-", "|-", ">+", "|+"):
            base = len(lines[idx]) - len(lines[idx].lstrip())
            while end < s1 and (not lines[end].strip()
                                or (len(lines[end]) - len(lines[end].lstrip())) > base):
                end += 1
        lines[idx:end] = [new_line]
    _validate_and_write("".join(lines), block_id, sim_type)


def set_boundary_param(block_id: str, net: str, key: str, value: str) -> None:
    """Set (or add) a param on a block boundary net's inline `params: { … }`."""
    lines = _lines()
    lo, hi = _block_range(lines, block_id)
    # find the boundaries: section, then the net's line
    bidx = None
    for i in range(lo, hi):
        if re.match(r"^\s*boundaries:\s*$", lines[i]):
            bidx = i
            break
    if bidx is None:
        raise CatalogEditError("block has no boundaries: section")
    bound_indent = len(lines[bidx]) - len(lines[bidx].lstrip())
    # net key may be quoted ("+3V3") or bare (LDO_EN); value is an inline dict.
    net_pat = re.compile(rf'^(\s*)("?{re.escape(net)}"?)\s*:\s*\{{(.*)\}}\s*(#.*)?$')
    nidx = None
    for i in range(bidx + 1, hi):
        s = lines[i]
        if not s.strip():
            continue
        cur_indent = len(s) - len(s.lstrip())
        # left the boundaries: block once we hit a key at boundaries' own indent
        if cur_indent <= bound_indent:
            break
        if net_pat.match(s):
            nidx = i
            break
    if nidx is None:
        raise CatalogEditError(f"boundary net {net!r} not found")
    m = net_pat.match(lines[nidx])
    indent, netkey, inner, comment = m.group(1), m.group(2), m.group(3), m.group(4) or ""
    # inner looks like: " stub: RailIn, params: { V: 3.3, R_src: 0.020 } "
    pm = re.search(r"params:\s*\{([^}]*)\}", inner)
    if not pm:
        raise CatalogEditError(f"net {net!r} has no params block")
    params_str = pm.group(1)
    # parse the comma-separated k: v pairs
    pairs: list[tuple[str, str]] = []
    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise CatalogEditError(f"unparseable param fragment {part!r}")
        k, v = part.split(":", 1)
        pairs.append((k.strip(), v.strip()))
    found = False
    for n, (k, _v) in enumerate(pairs):
        if k == key:
            pairs[n] = (k, value.strip())
            found = True
            break
    if not found:
        pairs.append((key, value.strip()))
    new_params = ", ".join(f"{k}: {v}" for k, v in pairs)
    new_inner = inner[:pm.start()] + f"params: {{ {new_params} }}" + inner[pm.end():]
    lines[nidx] = f"{indent}{netkey}: {{{new_inner}}}{(' ' + comment) if comment else ''}\n"
    _validate_and_write("".join(lines), block_id, None)


def requirements(block_id: str) -> dict:
    """Read-back: the editable requirements for a block — each sim_type's
    pass/rationale + the block's boundary params (post-merge is NOT applied here;
    these are the BASE editable values)."""
    from .catalog import get_block
    blk = get_block(block_id)
    sims = []
    for s in blk.get("sim_types", []):
        sims.append({
            "type": s["type"],
            "status": s.get("status", "implemented"),
            "rationale": (s.get("rationale") or "").strip(),
            "pass": s.get("pass"),
        })
    boundaries = {}
    for net, spec in (blk.get("boundaries") or {}).items():
        boundaries[net] = {"stub": spec.get("stub"), "params": spec.get("params", {})}
    return {"block": block_id, "sim_types": sims, "boundaries": boundaries}
