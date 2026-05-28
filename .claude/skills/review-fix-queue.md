---
name: review-fix-queue
description: Process queued component-review fixes — the user clicks "Apply" in the GUI Review tab, which writes a fix request to test1/review/fix_queue.json. This skill picks up queued requests, sanity-checks each suggested fix against the current netlist/symbol/layout, applies it (or rejects with a reason), rebuilds the project, and updates the queue status. Trigger when the user says "apply pending fixes", "process the queue", "apply the queued <refdes> fix", or asks what's in the review queue.
---

# Process queued review fixes

The Voltai PDF review flow is documented end-to-end in [[design_review]] / [[altium-launch-and-verify]]. This skill is the **agent-loop half** of that flow.

## When this fires

The user clicks **Apply** next to a finding in the GUI Review tab → the backend appends to [test1/review/fix_queue.json](test1/review/fix_queue.json) with `status: "queued"`. The button does **not** edit the design — it parks the request for the agent (me) to read, verify, and apply. Trigger phrases:

- "apply pending fixes" / "process the queue" / "any fixes pending?"
- "apply the queued U41 fix" (or any specific finding/refdes)
- After uploading a new review PDF, the user may ask me to triage it

## The queue file

`test1/review/fix_queue.json` is a list of entries shaped like:

```json
{
  "finding_id":   "38f28cc91bdc",
  "action_index": 0,
  "action_kind":  "fix" | "alt" | "verify",
  "action_text":  "Add a DC feedback network from @P:U41.OUTB to @P:U41.-INB ...",
  "component":    "U41",
  "category":     "Analog Signal Chain and Reference Integrity",
  "rule":         "@P:U41.OUTB ... shall not be directly connected to ...",
  "refs":         ["U41.OUTB", "U41", "U41.V+", "Net_+3V3"],
  "status":       "queued" | "applied" | "failed" | "dismissed",
  "queued_at":    1748409832.123
}
```

The matching finding (with `detail`, all `actions[]`, etc.) lives in [test1/review/findings.json](test1/review/findings.json) — load both when triaging.

## Process per queued entry

1. **Read the queue** and filter to `status == "queued"`. If empty, tell the user "no pending fixes" and stop.

2. **Cross-check the suggestion against the actual design.** Don't trust the review tool's claim that something is wrong — verify against the source of truth:
   - **Netlist YAML** (`test1/netlist/<sheet>.yaml`) — what nets the refdes is on.
   - **Symbol library** (`test1/Parts Library/<MPN>/<MPN>.SchLib`) — pin numbers/sides.
   - **Built `.SchDoc`** (`test1/altium/out/<sheet>.SchDoc`) — what's actually wired, including any geometric shorts the validator may have missed.
     Open it with `AltiumSchDoc("path.SchDoc")` and use `get_pins_for_component`, `get_wires`, `power_ports` to trace.
   - The validator and linter pass ≠ the design is correct; T-intersections of horizontal lanes with power-port stub endpoints are a known blind spot.

3. **Three possible verdicts:**
   - **Confirmed real defect** → apply the suggested fix (or a better one — explain in chat why).
   - **False positive** (the review tool misread the schematic) → mark `"status": "dismissed"`, write a `"dismissal_reason"` field explaining what the tool got wrong, and tell the user.
   - **Real defect but suggested fix is wrong** → propose the correct fix in chat, ask the user before applying.

4. **Apply with the existing builder primitives, not by hand-editing SchDoc binaries.** The flow is always:
   - Edit `test1/netlist/<sheet>.yaml` (the connectivity source of truth) and/or `test1/altium/build_<sheet>.py` (routing) and/or `test1/Parts Library/<MPN>/<MPN>.SchLib` (symbol fixes via `normalize_passive.py`, `author_symbol.py`, etc.).
   - Rebuild: `python -m test1.altium.build_project` (in the spike venv).
   - Verify: build must come back `FAILURES: none`. Sheet should be `0/0` E/W; if the original review caught something the in-repo linter doesn't, also propose a new linter rule (see [[altium-layout-linter]]).

5. **Update the queue entry** in place:
   ```python
   entry["status"] = "applied"             # or "failed"
   entry["applied_at"] = time.time()
   entry["applied_diff"] = "<short summary of what changed>"
   entry["new_lint"] = {"ERROR": 0, "WARNING": 0, "INFO": 6}  # from out/lint.json
   # on failure:
   entry["error"] = "<one-line reason>"
   ```
   Re-write `fix_queue.json` (overwrite, indent=2, utf-8).

6. **Report back in chat** with: which finding, what changed (file paths + 1-line diff), new lint state, whether you applied as-suggested or modified the suggestion (and why). Keep it concise.

## Backend endpoints involved

- `GET /api/findings` — the full findings list (envelope shape from the Voltai PDF parser); cross-reference here to find the matching action by `finding_id + action_index`.
- `GET /api/fix-queue` — the queue contents.
- `DELETE /api/fix-queue/{finding_id}` — drop an entry (user clicks "cancel" in the GUI). Don't call this from the agent — the user owns dismissals.

## What NOT to do

- **Don't apply the queue silently.** Always summarise in chat (the user is in the loop on purpose).
- **Don't trust the review tool's structured tags blindly.** `@N:Net_+3V3` is the tool's idea of a net name; our internal nets have different names (`+3V3`, `internal_OPA_chB_out_to_PMOS_gate`, etc.) — match by pin (refdes.pin), not by net name.
- **Don't add an `apply_silently` mode without explicit user authorisation** — the queue + chat handoff is by design (see [[gui-altium-backend]] for the rationale).
- **Don't hand-edit `.SchDoc` binaries.** Always go through the YAML → builder → rebuild path so the change is reproducible and the validator/linter gates run.

Related: [[design_review]] (the Voltai PDF parser), [[altium-circuit-from-topology]] (how the builders work), [[altium-layout-linter]] (the geometry gate).
