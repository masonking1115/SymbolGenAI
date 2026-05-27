"""Altium backend for the test1 generator (Gate 0 smoke test).

Mirrors the gen/ package structure but targets Altium binary files via
altium_monkey instead of KiCad s-expression text. netlist/*.yaml remains the
canonical source of truth; only this backend changes.
"""
