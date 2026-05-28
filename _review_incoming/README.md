# Component-review PDF drop folder

Drop the review PDF produced by the external review tool in this folder.
Once dropped, an installer + parser script (`install_review.py`, TBD — author
once a sample PDF is in hand) will:

1.  Parse the PDF into the `Finding[]` schema used by the existing Review tab:
    `{ severity: ERROR|WARNING|INFO, category, refs, message, detail,
       fix_hint, source }`
2.  Write `test1/review/findings.json` so the GUI Review tab picks it up via
    `GET /api/findings` and renders the Pass/Fail/Warning rows.
3.  Each row gets an **Apply fix** action that calls a new endpoint
    `POST /api/findings/{id}/apply`, which:
       - re-reads the relevant component/sheet from the netlist + symbol lib,
       - validates the suggested fix (sanity checks against design rules),
       - applies it via the existing builder primitives (edit YAML / re-author
         symbol / re-run build_project),
       - reports back the diff and the new lint state.

## What I still need from you

Before I can write the parser/installer, I need to see the PDF. Drop one in
this folder and tell me which format the external tool produces (see the
"Format checklist" section in the chat — I'll work to whichever applies).
