# Datasheet drop folder

Drop component datasheet PDFs in this folder, then run:

```powershell
c:/Users/mking/Downloads/altium_spike/.venv/Scripts/python.exe install_datasheets.py
```

Each PDF is matched against the `test1/Parts Library/<MPN>/` directories and
**moved** into the matching part folder. Matching is case-insensitive and
ignores hyphens/spaces, so any filename that contains the MPN works:

| Filename you drop                              | Lands in                              |
| ---------------------------------------------- | ------------------------------------- |
| `GRM155R71H103KA88D.pdf`                       | `Parts Library/GRM155R71H103KA88D/`   |
| `murata grm155r71h103ka88d datasheet rev3.pdf` | `Parts Library/GRM155R71H103KA88D/`   |
| `CR0402-FX-1001GLF.pdf`                        | `Parts Library/CR0402-FX-1001GLF/`    |
| `bourns_cr0402fx1001glf.pdf`                   | `Parts Library/CR0402-FX-1001GLF/`    |

Ambiguous (multiple MPNs in the filename) and unmatched files stay in place
and are listed in the report; rename to disambiguate and rerun.

## Why drop datasheets at all?

The build path (validator + layout linter + Altium output) does **not** read
PDFs — they are purely human-reference documentation that sits beside the
symbol and footprint inside each `Parts Library/<MPN>/` folder. Convention
matches the existing parts (e.g.
`Parts Library/24AA08-I-SN/24AA08-…-DS20001710.pdf`).

## Currently missing datasheets (as of last check)

The following committed MPNs have no PDF yet — drop one in here and the
allocator will route it:

- `CR0402-FX-1001GLF` (Bourns 1 kΩ, 0402)
- `CR0402-FX-2201GLF` (Bourns 2.2 kΩ, 0402)
- `GRM155R71H103KA88D` (Murata 10 nF, X7R, 50 V, 0402)
- `GRM21BR61A226ME44L` (Murata 22 µF, X5R, 10 V, 0805)
- `GRM21BR71A106KA73L` (Murata 10 µF, X7R, 10 V, 0805)
