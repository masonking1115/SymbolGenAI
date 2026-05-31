# 05 — Topology and polarity errors

Plants that change WHICH net a pin sits on (wrong rail, swapped pins, missing
component). These exercise the strict validator, the semantic evaluator's
`RAIL_*` / `PRESENT_*` / `ROUTE_*` rules, and — for behavioral changes — the
simulation. Many of these would survive the linter (the geometry is fine);
only the netlist analysis catches them.

**Index**
- TP-01 Op-amp +IN / −IN swapped → positive feedback
- TP-02 PMOS source/drain swapped
- TP-03 NMOS gate/source swapped on 2N7002
- TP-04 2N7002 D/S swapped (body diode forward)
- TP-05 LDO FB tied to load instead of OUT bus (kelvin lost)
- TP-06 LDO SNS shorted to GND
- TP-07 MCP4728 VDD tied to VADJ instead of +3V3
- TP-08 Bobcat VDDA1 cap on rail-side instead of chip-side
- TP-09 Pull-up on the wrong side of a 0 Ω
- TP-10 CS_L pulled DOWN instead of UP
- TP-11 SAMPLE_OUT3 / SAMPLE_OUT4 swapped
- TP-12 Bobcat NC pin (21) wired to GND
- TP-13 VDDIO wired directly to VADJ (load switch bypassed)
- TP-14 Bias jumper J11 missing → +VDDA1 floats
- TP-15 OPA2388 V+ tied to VADJ instead of +3V3

---

### TP-01 — Op-amp +IN / −IN swapped (channel 0 bias loop)

**Description.** Swap `U41.2` (−IN_A) and `U41.3` (+IN_A) in their
respective net memberships. The bias loop becomes positive feedback — the
op-amp rails to one supply and the PMOS either fully on or fully off.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Edits:
  - `internal_VOUTA_to_OPA_pos.members`: change `U41.3` → `U41.2`.
  - `internal_PMOS0_source_feedback.members`: change `U41.2` → `U41.3`.

**Detect.**
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_LOOP_STABILITY`
- Severity: ERROR
- Expected: opamp output rails immediately; bias current = 0 or FS regardless
  of DAC code.

Also:
- Tool: semantic (planned)
- Rule/ID: `SEM_OPAMP_FEEDBACK_POLARITY`
- Severity: ERROR

**Fix.** Swap back.

**Pass criteria.**
- Sim emits non-convergence OR shows rail-to-rail output.
- Plan correctly identifies the polarity swap, not "tune the loop."

---

### TP-02 — PMOS source/drain swapped

**Description.** Swap Q40 source (pin 2) and drain (pin 3) net memberships.
With the body diode oriented backwards, current sources straight from +3V3 to
the BIASx pin through the body diode, uncontrolled.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Edits:
  - `internal_PMOS0_source_feedback.members`: replace `Q40.2` with `Q40.3`.
  - `internal_BIAS0_drain_stub.members`: replace `Q40.3` with `Q40.2`.

**Detect.**
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_DEFAULT_OFF` (always-on current) OR
  `BLK_BIAS_LOOP_STABILITY`.
- Severity: ERROR

Also:
- Tool: semantic
- Rule/ID: `SEM_BIAS_SOURCE_INTO_PIN` (current direction)
- Severity: ERROR

**Fix.** Swap back.

---

### TP-03 — NMOS gate/source swapped on Q42

**Description.** Swap Q42 gate (1) and source (2). FPGA's BIAS_ISO drive now
fights the source node directly.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Edits:
  - `BIAS_ISO0.members`: replace `Q42.1` with `Q42.2`.
  - `BIAS0.members`: replace `Q42.2` with `Q42.1`.

**Detect.**
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_ISO_PULLDOWN` (the pull-down now sits on the source
  not the gate)
- Severity: ERROR

Also:
- Tool: semantic
- Rule/ID: `PULLDOWN_BIAS_ISO0` (pull-down attached to wrong pin)
- Severity: ERROR

**Fix.** Swap back.

---

### TP-04 — 2N7002 D/S swapped → body diode forward in normal op

**Description.** Swap drain (3) and source (2). Body diode now forward-biases
during normal operation, leaking current regardless of gate state.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Edits:
  - `internal_BIAS0_drain_stub.members`: replace `Q42.3` with `Q42.2`.
  - `BIAS0.members`: replace `Q42.2` with `Q42.3`.

**Detect.**
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_POR_FAILSAFE` (current leaks even with gate LOW)
- Severity: ERROR

**Fix.** Swap back.

---

### TP-05 — LDO FB tied to load instead of OUT bus

**Description.** ANY-OUT mode requires FB strapped to OUT/SNS. Wiring FB to
the load-side of the jumper means the LDO regulates whatever rail happens to
be jumpered — and three rails fight for one feedback point.

**Plant.**
- File: `test1/netlist/power.yaml`
- Key: `internal_LDO_OUT_bus.members`
- Change: remove `U10.3` (FB) and add it to a new net `+VDDA1` member or
  to `J11.1` (load-side of VDDA1 jumper).

**Detect.**
- Tool: semantic
- Rule/ID: `SEM_LDO_FB_STRAP` (planned)
- Severity: ERROR

Also:
- Tool: sim
- Block: `ldo_rail`
- Rule/ID: `BLK_LDO_DC_OK` — output drifts with load.
- Severity: ERROR

**Fix.** Restore FB on OUT bus.

**Notes.** `design_intent.md` "U10 FB/SNS are strapped to OUT" — the rule
must exist; if not, this test surfaces the gap.

---

### TP-06 — LDO SNS shorted to GND

**Description.** Pull SNS to GND. LDO drives output to compensate, oscillates
or rails high.

**Plant.**
- File: `test1/netlist/power.yaml`
- Move `U10.2` (SNS) from `internal_LDO_OUT_bus` to `GND`.

**Detect.**
- Tool: sim
- Block: `ldo_rail`
- Rule/ID: `BLK_LDO_DC_OK`
- Severity: ERROR
- Expected: output rails to ~5 V (or the headroom limit).

Also:
- Tool: semantic
- Rule/ID: `SEM_LDO_FB_STRAP`
- Severity: ERROR

**Fix.** Restore SNS on OUT bus.

---

### TP-07 — MCP4728 VDD tied to VADJ instead of +3V3

**Description.** External VREF=VDD config bit means DAC output range = VDD.
Tying VDD to VADJ makes the DAC range track VADJ — at VADJ=1.2 V the DAC can
only output 0–1.2 V, and PMOS source ≈ +3V3 always → PMOS off, no bias.

**Plant.**
- File: `test1/netlist/bias.yaml`
- Move `U40.1` from `+3V3` net to `VADJ` net.

**Detect.**
- Tool: semantic
- Rule/ID: `RAIL_MCP4728_VDD`
- Severity: ERROR

Also:
- Tool: sim
- Block: `opa_bias`
- Rule/ID: `BLK_BIAS_FS_CEILING` (FS drops with VADJ)
- Severity: ERROR

**Fix.** Restore MCP4728 VDD on +3V3.

---

### TP-08 — Bobcat VDDA1 cap moved to rail-side of R20

**Description.** C22 (VDDA1 decoupling) should sit on the CHIP side of R20
(post-resistor); moving it to the rail side defeats the series-R noise
isolation.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Move `C22.1` from `internal_VDDA1_path` to `+VDDA1`.

**Detect.**
- Tool: semantic
- Rule/ID: `DECOUPLE_VDDA1` (position check, if implemented)
- Severity: ERROR

**Fix.** Restore C22.1 on the chip side.

**Pass criteria.**
- Rule fires.
- Plan distinguishes "moved cap" from "missing cap" — the right action is to
  move, not add a new one.

---

### TP-09 — Pull-up on wrong side of 0 Ω

**Description.** R24 (CS_L pull-up) currently sits on the +VDDIO side of the
chip pin. Move it to the FMC side of the R109 0 Ω so the pull-up disconnects
when the LA-bank R is depopulated.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Add `R109` as the pivot (already in `fmc.yaml`); change R24 wiring to land
  on `R109.2` instead of `U20.17`.

**Detect.**
- Tool: semantic
- Rule/ID: `PULLUP_CS_L` (with side-of-jumper check)
- Severity: WARNING

**Fix.** Restore R24 on the chip side.

---

### TP-10 — CS_L pulled DOWN instead of UP

**Description.** Replace the CS_L pull-up (R24, 10 k to +VDDIO) with a
pull-down. At POR, CS_L = LOW = SPI device selected — accidental SPI traffic
on power-up.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Move `R24.1` from `+VDDIO` to `GND`.

**Detect.**
- Tool: semantic
- Rule/ID: `PULLUP_CS_L`
- Severity: ERROR

Also:
- Tool: sim
- Block: `system_sequencing` (if it models POR I/O state)
- Severity: ERROR

**Fix.** Restore pull-up to +VDDIO.

---

### TP-11 — SAMPLE_OUT3 / SAMPLE_OUT4 swapped

**Description.** Pin reassignment regression: swap which Bobcat pin maps to
each SAMPLE_OUT global. Validator notices the membership swap; semantic
ROUTE_* rule catches the cross-sheet contract break.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Edits:
  - `SAMPLE_OUT3.members`: `U20.6` → `U20.8`.
  - `SAMPLE_OUT4.members`: `U20.8` → `U20.6`.

**Detect.**
- Tool: semantic
- Rule/ID: `ROUTE_SAMPLE_OUT3` and `ROUTE_SAMPLE_OUT4`
- Severity: ERROR

**Fix.** Swap back.

---

### TP-12 — Bobcat NC pin (21) wired to GND

**Description.** Bobcat datasheet pin 21 is NC. Wiring it to GND is harmless
on most chips but spec-violating; semantic should flag.

**Plant.**
- File: `test1/netlist/bobcat.yaml`
- Add `U20.21` to the `GND` net members.

**Detect.**
- Tool: semantic
- Rule/ID: `NC_BOBCAT_PIN_21` (planned)
- Severity: WARNING

**Fix.** Remove the membership; let the build assign No-ERC.

**Anti-test.** Wiring it to a hier-label (`BOBCAT_NC1`) should be a clearer
ERROR — a phantom signal would propagate.

---

### TP-13 — VDDIO wired directly to VADJ (load switch bypassed)

**Description.** Remove `U11.A1` from `+VDDIO` and replace with the VADJ net
directly. Load switch is electrically present but bypassed.

**Plant.**
- File: `test1/netlist/power.yaml`
- Edits:
  - `+VDDIO.members`: remove `U11.A1`.
  - Add `+VDDIO.members` += `VADJ`-equivalent (or change the `VADJ` net to
    also be named `+VDDIO`).

**Detect.**
- Tool: semantic
- Rule/ID: `BLK_LOADSW_VDDIO_PATH` (path-must-include rule)
- Severity: ERROR

**Fix.** Restore U11.A1 on +VDDIO.

---

### TP-14 — Bias jumper J11 missing → +VDDA1 floats

**Description.** Remove J11 (the VDDA1 selection jumper). +VDDA1 has no
source. Bobcat VDDA1 floats.

**Plant.**
- File: `test1/netlist/power.yaml`
- Action: delete the `J11:` part block AND all member references to `J11.1`,
  `J11.2`.

**Detect.**
- Tool: semantic
- Rule/ID: `JUMPER_VDDA1` and `PRESENT_LDO_JUMPER_VDDA1` (if exists)
- Severity: ERROR

Also:
- Tool: validator
- Rule/ID: `+VDDA1` net has only Bobcat-side membership; no LDO-side source.
- Severity: ERROR

**Fix.** Restore J11.

---

### TP-15 — OPA2388 V+ tied to VADJ instead of +3V3

**Description.** Move U41.8 from +3V3 to VADJ. Op-amp supply now scales with
VADJ; at VADJ=1.2 V the op-amp can't even start (Vsupply < 2.5 V min).

**Plant.**
- File: `test1/netlist/bias.yaml`
- Move `U41.8` from `+3V3` to a new `VADJ` net (hier or internal).

**Detect.**
- Tool: semantic
- Rule/ID: `RAIL_OPA2388_VPLUS`
- Severity: ERROR

Also:
- Tool: sim
- Block: `opa_bias`
- Rule/ID: any opamp-supply-range check (planned).
- Severity: ERROR at VADJ < 2.5 V.

**Fix.** Restore U41.8 on +3V3.

---

## Notes on detection coverage

The pattern across this category is:
- **validator** catches missing/extra members and direction mismatches.
- **semantic** catches RAIL/ROUTE/PRESENT family.
- **sim** catches behavioral consequences.

If any single plant fires fewer than two of those three layers, that's
typically a coverage gap — the harness should make the gap explicit.
