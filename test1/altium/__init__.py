"""Altium backend for the test1 generator.

Mirrors the gen/ package structure but targets Altium binary files via
altium_monkey instead of KiCad s-expression text. netlist/*.yaml remains the
canonical source of truth; only this backend changes. The top-level entry point
is `python -m test1.altium.build_project`.
"""
