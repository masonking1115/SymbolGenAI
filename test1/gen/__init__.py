"""gen — shared netlist/symbol layer for the test1 generator.

Originally the KiCad schematic generator package; the per-sheet KiCad
builders have been retired in favor of the Altium backend (`test1.altium`).
What remains is the backend-neutral core that the Altium builders import:

  config.py     — constants, paths, uid(), SHEET_*, LA_ASSIGN, PARTS_LIB
  symbols.py    — pin-spec parsing (parse_pins) + symbol-text helpers
  netlist.py    — load_netlist(), Net/Netlist, parse_member()
  validator.py  — validate(): electrical connectivity checks
  shared.py     — Sheet container (used by validator's type surface)
"""
