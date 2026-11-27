"""Validator input derived straight from the raw Factory records.

validate_coupled_plan used to import _sku_data/_recipe_data/due_day from
the model (two_level.py). A defect in those helpers (the 2026-11-26
duplicate-lines incident was one) then reached the model and its
"independent" validator together, and the plan passed. These functions
re-derive the same facts from operations, loads, materials and demands
with no import from the rolling/ modules, so a corrupted model helper
produces a plan the validator can still refuse.

Facts, taken from the records only:
 rate     units per minute = 1 / (minutes of operation.duration_per)
 lines    resources named by the operation's loads (set, no duplicates)
 recipe   raw material -> units consumed per unit produced (negative
          material quantities); product = the operation's positive item
 due day  day index whose END is the due time (a midnight due closes
          the day before it)
Only the operation's first positive material is the product, as in the
record schema (one product per operation).
"""
from __future__ import annotations

from datetime import timedelta

_EPSILON = timedelta(microseconds=1)


def raw_sku_data(factory) -> dict:
    """sku -> (rate per minute, sorted eligible lines, setup state)."""
    out: dict = {}
    for op in factory.operations:
        products = [m.item for m in op.materials if m.quantity > 0]
        minutes = op.duration_per.total_seconds() / 60.0
        if not products or minutes <= 0:
            continue
        lines = sorted({ld.resource for ld in op.loads})
        setup = None
        for ld in op.loads:
            if ld.setup:
                setup = ld.setup
                break
        out[products[0]] = (1.0 / minutes, lines, setup)
    return out


def raw_recipe_data(factory) -> dict:
    """sku -> {raw material: units per unit produced}."""
    out: dict = {}
    for op in factory.operations:
        products = [m.item for m in op.materials if m.quantity > 0]
        used = {m.item: -m.quantity for m in op.materials
                if m.quantity < 0}
        if products and used:
            out[products[0]] = used
    return out


def raw_due_day(due, horizon_start) -> int:
    return (due - horizon_start - _EPSILON).days
