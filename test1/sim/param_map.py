"""Map agent-extracted datasheet values → canonical ngspice model params.

The sim_interpret agent extracts rich, cited datasheet values into the cache
(many conditions, mixed units). The ngspice models, though, take specific
named params in base SI units. This module is the deterministic bridge: it
picks the right datasheet number (worst-case where it matters) and converts
units, producing exactly the params each subcircuit declares.

Why code, not the agent: the "which value / what unit" choice is engineering
judgment that should be reviewable and reproducible, not re-derived by an LLM
each run. The agent extracts; this maps. A part with no mapping falls back to
the model's built-in defaults (graceful).
"""

from __future__ import annotations

from . import dscache


def _pick(entry: dict, *keys):
    """First present key across model_params + spec."""
    pool = {**entry.get("model_params", {}), **entry.get("spec", {})}
    for k in keys:
        if k in pool and pool[k] is not None:
            return pool[k]
    return None


def _ldo_tps7a8401a(e: dict) -> dict:
    out: dict[str, float] = {}
    # Worst-case dropout (with BIAS, since +3V3 drives the BIAS pin), mV→V.
    d_mv = _pick(e, "DROPOUT_mV_max_VIN1V1_BIAS_3A", "DROPOUT_mV_max_VIN1V4_3A")
    if d_mv is not None:
        out["DROPOUT"] = d_mv / 1000.0
    lr = _pick(e, "LINE_REG_mVperV_typ")          # mV/V → V/V
    if lr is not None:
        out["LINE_REG"] = lr / 1000.0
    return out


def _sw_tps22916(e: dict) -> dict:
    out: dict[str, float] = {}
    ron_mohm = _pick(e, "RON_mOhm_max_VIN1V8_85C", "RON_mOhm_typ_VIN1V8_25C",
                     "RON_mOhm_max_at_1V8_85C")
    if ron_mohm is not None:
        out["RDSON"] = ron_mohm / 1000.0
    ton_us = _pick(e, "tON_us_typ_VIN1V8")        # turn-on time, µs → s
    if ton_us is not None:
        out["TRISE"] = ton_us / 1e6
    return out


def _opa2388(e: dict) -> dict:
    out: dict[str, float] = {}
    vos_uv = _pick(e, "VOS_uV_max_25C", "VOS_uV_typ_25C")  # worst-case offset
    if vos_uv is not None:
        out["VOS"] = vos_uv / 1e6
    gbw_mhz = _pick(e, "GBW_MHz")
    if gbw_mhz is not None:
        out["GBW"] = gbw_mhz * 1e6
    aol_db = _pick(e, "AOL_dB_min", "AOL_dB_typ")          # worst-case (min) gain
    if aol_db is not None:
        out["AOL"] = 10 ** (aol_db / 20.0)
    return out


# MPN (as tagged in blocks.yaml) → (ngspice model name, mapper).
_MAP = {
    "TPS7A8401A": ("LDO_TPS7A8401A", _ldo_tps7a8401a),
    "TPS22916CNYFPR": ("SW_TPS22916", _sw_tps22916),
    "OPA2388": ("OPA2388", _opa2388),
}


def applied(mpn: str) -> dict[str, float]:
    """Canonical ngspice params for this part from the cache, or {} if the
    part isn't cached / has no mapping (→ model defaults apply)."""
    e = dscache.entry(mpn)
    if not e or mpn not in _MAP:
        return {}
    return _MAP[mpn][1](e)


def params_string(mpn: str) -> str:
    """Render applied params as a SPICE `PARAMS:` suffix, e.g. ' DROPOUT=0.18'."""
    return "".join(f" {k}={v:.6g}" for k, v in applied(mpn).items())
