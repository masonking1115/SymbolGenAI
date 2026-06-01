# External review (2026-05-31) — independent verification + verdicts

> STATUS (end of pass): ALL findings independently verified — every substantive
> one is REAL. FIXED in-source: F-2 (LDO setpoint names → true 8401A weights),
> F-6 (3 footprints → datasheet packages), F-4 (BOM regenerated). LOGGED for HW
> decision in design_requirements.md: F-1 (GND — fix blocked on a trusted VITA
> 57.1 LPC GND pin list), F-3 (NMOS gate drive), F-5 (gate-stop R), F-7 (bulk
> caps). Post-fix: rebuild 0/0/0, cross-sheet LDO_SET nets match, 30/30 review
> tests, full review loop → all_clear (which ALSO confirms the loop's blind spots
> to F-1/F-3 — see tooling improvements).


My independent re-review of another agent's findings, checked against the actual
sources (netlist yaml, build_*.py, parts.SchLib/BOM, datasheets via web, sim,
design_requirements.md). Verdict legend: CONFIRMED / REFUTED / PARTIAL.

================================================================================
## CRITICAL
================================================================================

### F-1. FMC connector GND pins floating in the netlist — **CONFIRMED (real defect)**
Evidence:
- `build_fmc.py:211-218` explicitly `s.no_connect()` on EVERY unwired pin
  ("NC every remaining pin … uncovered by validation, kept clean to avoid any
  false unions on this dense layout").
- The build wires exactly 44 of 160 pins: 4×+3V3 (C39,D36,D38,D40) + 3×GND-strap
  (H2,C34,D35) + 2×VADJ + 1×LDO_PG + 2×I²C + 4×intentional-NC + 28×LA-bank.
- `fmc.yaml` GND net has ONLY 3 members (H2, C34, D35). The ~60 VITA-57.1 LPC GND
  pins are NOT on the GND net.
- The `fmc.yaml` top comment ("GND … bussed per-row from all unrouted/non-named
  pins onto a single GND symbol … the mass GND-bussed pins are uncovered by
  validation") is ASPIRATIONAL — the code does the opposite (No-ERC).
- Symbol pins are Electrical=Passive (not Power/Name=GND), so nothing auto-merges.
Consequence: in a schematic→PCB flow, ~60 connector GND pads are unconnected —
no signal return for the LA pairs, no supply return, no proximity ground.
Severity: HIGH-CONFIDENCE real. (Only escape hatch would be a layout-level pour
tying the pads, but with Passive unconnected pins the netlist won't enforce it —
fragile and not the documented intent.)

### F-2. TPS7A8401A setpoint net names off-by-one (8400A naming on 8401A) — **CONFIRMED**
Datasheet (TI TPS7A84A, SBVSxxx): 8401A pins 5/6/7/9/10/11 = 25/50/100/200/400/800 mV,
base 0.5 V, 25 mV/LSB. 8400A = 50/100/200/400/800/1600 mV, base 0.8 V, 50 mV/LSB.
Grounding a SET pin ADDS its weight.
Schematic actual nets (power.yaml ↔ U10 pins, confirmed):
  U10.5→LDO_SET_50mV (real 25mV) · U10.6→LDO_SET_100mV (50) · U10.7→LDO_SET_200mV (100)
  U10.9→LDO_SET_400mV (200) · U10.10→LDO_SET_800mV (400) · U10.11→LDO_SET_1V6 (800)
=> every net name is the 8400A label = 2× the real 8401A weight. Names propagate
identically through power.yaml, fmc.yaml, build_power.py, build_fmc.py, and the render.
Electrical wiring is self-consistent; only the NAMES misrepresent the bits → an
FPGA mapping by name writes the wrong bit. CONFIRMED.
Correction to the external review's arithmetic (theirs had errors but the gist holds):
  0.6 V = 500+100 → ground the 100mV bit = pin 7 (schematic-named LDO_SET_200mV). ✓
  1.0 V = 500+500 = 500+(400+100) → ground pins 10 & 7 (named LDO_SET_800mV & _200mV).
  (So 1.0 V IS reachable — the review's "1.0 V impossible" tangent was wrong, but
   the naming defect they flagged is correct and is the real issue.)

### F-3. Bias NMOS (2N7002) only conducts at VADJ ≥ ~2.5 V — **CONFIRMED**
- BIAS_ISO0/1 = LA20_P(G21) / LA21_P(H25) — FMC LA-bank pins; on Genesys 2 the LA
  VCCO = VADJ, so FPGA VOH on these = VADJ.
- design_requirements.md:7 explicitly allows "VADJ 1.2–3.3 V".
- 2N7002 V_GS(th) = 1.0 V min / 2.5 V max (standard, NOT logic-level) — confirmed
  onsemi/Nexperia/Diodes. R_DS(on) only spec'd at V_GS≥4.5 V; subthreshold below Vth.
- Source at V_BIASx ≈ 0.5 V ⇒ V_GS = VADJ − 0.5. At VADJ=1.2 V → V_GS=0.7 V (OFF);
  1.8 → 1.3 (marginal); 2.5 → 2.0 (borderline); 3.3 → 2.8 (OK).
- Genesys 2 default VADJ = 1.2 V (JP6) ⇒ bias path OPEN by default.
CONFIRMED. The only way to pass bias at low VADJ is to populate the R42/R43 D-S
short, which forfeits the POR fail-safe. Real electrical limitation.

================================================================================
## HIGH / MEDIUM
================================================================================

### F-4. BOM stale on R40/R41 — **CONFIRMED**
test1_bom.xlsx Per-Refdes: R40/R41 = "5.11k 0.1% / TNPW06035K11BEEA / 5.11 kΩ 0603".
Live netlist (bias.yaml) + symbol lib = 3.65k / TNPW06033K65BEEA (verified). The
xlsx wasn't regenerated after the 2026-05-30 sense-R change. (The 5.11k strings in
build_bias.py are intentional historical annotation text — legitimate; the stale
artifact is the .xlsx.) CONFIRMED — regenerate the BOM.

### F-5. No gate-stop R between OPA2388 out and PMOS gate — **CONFIRMED (observation)**
internal_OPA0/1_out_to_PMOS_gate nets = exactly {U41.1,Q40.1} / {U41.7,Q41.1} —
direct, no series R. Whether it's NEEDED is judgment (slow I²C-rate bias → low
oscillation risk), but the observation is factually correct. The sim covers DC +
PDN, NOT bias-loop AC/transient stability — a real coverage gap. Worth an AC/step
sim before fab; a 100Ω–1kΩ gate series + small comp cap is the standard precaution.

### F-6. Footprint string vs orderable MPN/BOM mismatch — **CONFIRMED**
- U40 MCP4728: yaml `VQFN-10-1EP_3x3mm` vs BOM "MSOP-10" (DS22187E documents MSOP-10).
- U41 OPA2388: yaml `SOIC-8_3.9x4.9mm` vs BOM "MSOP-8" (VSSOP/MSOP, 3×3).
- Q40/Q41 PMZ1200UPEYL: yaml `DFN-3-1EP_1.0x1.0mm` vs BOM "SOT-666"; review says
  datasheet is SOT883 (1.0×0.6, no EP). Three-way disagreement.
All same pin-count so the NETLIST is fine, but the land patterns are wrong for PCB.
CONFIRMED — reconcile footprint: to the actual ordered package + library land pattern.

### F-7. No per-rail bulk decap on Bobcat side — **CONFIRMED**
bobcat sheet caps = {0.1uF×8, 1uF×2}; ALL bulk (10uF C10, 22uF C13/C18) lives on
the power sheet (LDO output bus, pre-jumper). design_requirements.md template wants
10µF+1µF+0.1µF per Bobcat rail. The jumper loop adds L/R between bulk and DUT.
CONFIRMED — adding a 10µF post-jumper at +VDDD/+VDDA1/+VDDA2 is cheap insurance.

================================================================================
## LOWER PRIORITY
================================================================================
- F-8 R60/R61 I²C pull-ups (2.2k, NOT dnp): CONFIRMED present + W4 already flags the
  bring-up DNP question. Valid.
- F-9 Virgin MCP4728 → uncontrolled bias: CONFIRMED already mitigated (Q42/Q43 +
  R44/R45, documented in reqs lines 108/110). Firmware-sequence reminder. Valid.
- F-10 Diff carrier-side NC (CLK/GBTCLK/DP): these names aren't in fmc.yaml → they
  fall into the blanket-No-ERC bucket (same mechanism as F-1). Acceptable per VITA
  when unused. Valid (and intertwined with F-1's handling).
- F-11 JTAG NC: matches reqs, intentional. Valid.

================================================================================
## "Checked and fine" — spot-verified
================================================================================
- BIAS FS headroom R_sense=3.65k: sim deck reports full_scale_A=vdd/r_sense and
  i_max_regulated_A; 640µA spec lands in-region. Consistent with the deck. ✓
- 6 sheets lint: lint.json status=pass, ERROR 0, WARNING 0. ✓
- ANY-OUT reach 0.6–1.0V on 8401A: addressable (see F-2 arithmetic). ✓ modulo naming.

================================================================================
## NET ASSESSMENT
================================================================================
The external review is HIGH QUALITY. Every substantive finding I checked is
accurate. F-1 (GND) is the most serious and is unambiguously real in the netlist.
F-2 (setpoint names) and F-3 (NMOS gate drive) are real and matter for firmware /
low-VADJ operation. The only error in the review was a garbled arithmetic tangent
in F-2 (claimed 1.0V unreachable — it's reachable); the core naming defect stands.

================================================================================
## WHAT I CAN FIX IN-NETLIST NOW vs. NEEDS-DECISION
================================================================================
FIXABLE deterministically in sources (no judgement / no new parts):
- F-2 rename LDO_SET_* nets to true 8401A weights (or generic LDO_SET[0..5]) across
  power.yaml + fmc.yaml + build_power.py + build_fmc.py + design_requirements.md.
- F-1 add the VITA-57.1 LPC GND pin positions to fmc.yaml's GND net so build_fmc
  wires them (needs the authoritative GND pin list — verify carefully, since a
  wrong pin here re-creates the C↔D-swap class of bug).
- F-4 regenerate test1_bom.xlsx from current netlist.
NEEDS A HUMAN/HW DECISION (won't silently change):
- F-3 part swap (2N7002 → low-Vth like Si2302) OR document "bias requires VADJ≥2.5V".
- F-5 add gate resistor (+ AC sim) — design choice.
- F-6 footprint corrections — needs the chosen ordered package + PCB land pattern.
- F-7 add post-jumper bulk caps — design choice (cheap, recommended).

================================================================================
## F-1 RESOLUTION STATUS (2026-05-31) — investigated, fix BLOCKED on trusted data
================================================================================
Chosen fix (per user): make the FMC symbol's GND pins Power/Name=GND so they
auto-merge. BLOCKER discovered: the Samtec UL symbol (Parts Library/ASP-134606-01/
ASP-134606-01.SchLib, imported from _ul_incoming/ul_ASP-134606-01.zip) names every
pin by its POSITION (C1, C2, …), NOT by function — so there are 0 pins named "GND"
to merge, and BOTH fix paths (symbol-rename or fmc.yaml enumeration) require the
explicit list of which ~60 positions are GND.

I could not obtain a TRUSTWORTHY GND pin list:
- fmchub.github.io fetch returned a GND list that, cross-checked against our OWN
  validated non-GND pins (LA_ASSIGN P-pins + power/special), COLLIDES on 14 pins
  it calls GND but which are real signals here (C1=LDO_PG, D8=SAMPLE_OUT0,
  D14=CS_L, D20=SAMPLE_TRIG, D26=LDO_SET_400mV, G12=SAMPLE_OUT7, G18=WEIGHT_EN,
  G24=LDO_SET_25mV, H13=SAMPLE_OUT6, H19=OSC_EN, H25=BIAS_ISO1, H2=PRSNT, C34=GA0,
  D35=GA1). => that source is WRONG (mezz/carrier or HPC/LPC column confusion).
  Baking it in would short 14 signals to GND — the exact class of bug the project
  already fixed once (the C↔D swap).
- Samtec product page: HTTP 403. Wikipedia: no pin-level table.

Quantified defect (built netlist): GND net = 3 members; 120 of 160 connector pins
are on NO net (No-ERC). ~60 should be GND.

SAFE fix paths (need a verified VITA 57.1 LPC GND list — from the spec PDF or the
Samtec datasheet, cross-checked so NONE of the 44 known non-GND pins appear in it):
 (a) Add those GND positions to fmc.yaml's GND net + change build_fmc.py to WIRE
     them to a GND bus instead of the blanket No-ERC at lines 211-218; or
 (b) Re-author/patch the symbol so those positions are Electrical=Power Name="GND"
     (auto-merge). Either way the cross-check `GND ∩ trusted_nongnd == {}` MUST
     pass before committing. Verification harness already written (the collision
     check above). RECOMMEND not implementing until the trusted list is in hand.

================================================================================
## REVIEW RULES ADDED (2026-05-31) — the loop now CATCHES these classes
================================================================================
Four GROUNDED rules added to gen_block_rules.py → merged into rules.yaml (119 total).
Each cites BOTH a design_requirements.md quote AND the part datasheet (in
Parts Library/<MPN>/), so the threshold/expected value lives in the cited source,
NOT in a prompt I wrote (per the "rules must not be biased by me" directive). All
verified: fire on the real/injected defect, pass on the corrected design, 3×
deterministic, 30/30 review unit tests, and confirmed in the live review loop.

- **BLK_LDO_SETPOINT_NAMING** (F-2, ERROR) — cites Specs + tps7a84a.pdf pin table
  ("50 mV (25 mV) …"). Verifies LDO_SET_* names = the 8401A (low-range) weight of
  each pin. Inject 8400A label → FAIL; current (fixed) design → PASS.
- **BLK_BIAS_ISO_GATE_DRIVE** (F-3, WARNING) — cites VADJ 1.2–3.3 V (reqs) +
  2n7002.pdf VGS(th) 1.0–2.5 V. Checks V_GS=VADJ−0.5 vs Vth across the full VADJ
  range. Current design → FAIL (correctly catches the open defect).
- **BLK_FOOTPRINT_MATCHES_DATASHEET** (F-6, WARNING) — cites each part datasheet's
  package (MCP4728 MSOP-10, OPA2388 VSSOP-8, PMZ1200 SOT883). Needed a fix:
  `footprint` was NOT in the semantic netlist-context, so the judge was starved of
  data and passed by default — added `footprint=` to the part lines in
  rule_eval._netlist_context_for. Now: inject wrong footprint → FAIL; fixed → PASS.
- **BLK_FMC_GND_PINS_TIED** (F-1, ERROR) — cites the "unlabeled C/D/G/H pins are GND"
  requirement + ASP-134606-01.pdf (VITA 57.1 LPC ~60 GND pins). Checks how many
  connector pins reach the GND net. Current design → FAIL (only 3 on GND; catches
  the open defect).

NOTE: the loop's apply agents TIME OUT trying to auto-fix F-1/F-3 (they're genuinely
not auto-fixable — F-1 needs a trusted GND pin list, F-3 needs a part swap / HW
call). That's the correct behavior: the loop flags them and holds rather than
inventing a fix. They stay OPEN until the human/data input below is provided.

================================================================================
## PROCESS / TOOLING IMPROVEMENTS (for future use) — see user request
================================================================================
Theme: the closed-loop review (structural lint + semantic + sim) did NOT catch
F-1, F-2, F-3, F-6, F-7. These are the gaps to close so the LOOP finds them next
time. (Per the standing "no fundamental linter changes" constraint these are
RECOMMENDATIONS, not changes I made unprompted.)

1. **F-1 blind spot — off-net / No-ERC pins are invisible to the netlist view.**
   The single highest-value catch. A VITA-57.1 power connector with 120/160 pins
   No-ERC'd and only 3 on GND is a glaring red flag, but every review layer reads
   the *netlist*, where off-net pins simply don't appear. Options:
   - A LAYOUT-LINT check (it already counts No-ERC objects on the built sheet):
     "connector with ≥N power pins but a No-ERC ratio > X% → WARN" .
   - A semantic rule fed the connector's TOTAL symbol-pin count vs wired count
     (so the judge sees "157/160 pins unconnected on a power connector").
   - A connector-GND structural predicate: "a connector carrying supply pins must
     have ≥K pins on GND." Needs a per-connector expected-GND hint.
   Also: the fmc.yaml comment described a GND bus that the builder never built —
   a doc/impl drift the loop can't see. A check that the builder's wired pins match
   the yaml's stated intent would catch aspirational comments.

2. **F-2 class — value/label semantics the netlist can't self-check.** The LDO
   setpoint names were internally consistent (so structural passed) but
   semantically wrong vs the PART (8401A vs 8400A). Mirroring the MPN-value decoder
   work: a rule that cross-checks pin-FUNCTION names against the part's datasheet
   pin table (e.g. "a pin named LDO_SET_800mV should be the 800mV ANY-OUT bit of
   THIS orderable part") would catch part-variant/labeling mismatches.

3. **F-3 class — operating-condition / level-compatibility checks.** No layer
   verified that a FET gate driven from a variable rail (VADJ 1.2–3.3V) actually
   exceeds the device Vth across the rail's RANGE. A semantic rule that, for each
   FET/logic interface, checks drive-voltage vs threshold across the documented
   supply range (datasheet Vth vs the min rail) would catch F-3-class issues. The
   sim could add a bias-loop AC/step test (covers F-5 too).

4. **F-6 class — footprint vs orderable-package consistency.** The netlist
   footprint string and the BOM/datasheet package disagreed on 3 parts. A rule
   cross-checking `footprint:` against the part's datasheet package (or the BOM's
   stated package) would catch land-pattern mismatches. Same engine as the MPN
   decoder.

5. **F-4 class — BOM regenerated-from-source freshness.** The BOM was a stale
   committed artifact. Either (a) regenerate it in the build (so it can't drift),
   or (b) a CI check that diffs the committed BOM against a fresh generate and
   fails on drift.

6. **F-7 — decoupling-topology / bulk-cap placement.** The decap COUNT rules
   passed, but bulk caps sit pre-jumper, not at the DUT. A rule that checks bulk
   caps are on the same side of any series element (jumper/0Ω) as the load pin
   they serve would catch this.

7. **General: simulate across the SPEC RANGE, not a nominal point.** F-3 (and
   arguably F-2's reachability) are corner-case failures. Sim scenarios that sweep
   each supply across its documented min/max (VADJ 1.2–3.3, VOUT 0.6–1.0) would
   surface range-dependent failures the nominal-point sims miss.
