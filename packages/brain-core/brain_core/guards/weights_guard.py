"""Objective-weights guard for cross-row comparisons (CG vs monolith).

A comparison with different weights measures the weights. A row states its
weights in `weights` ({setup, late, early, energy}) or, for the old monolith
calibration rows, only `calibration.setup_weight` (EOQ-calibrated per row,
2.3-24.8 measured). `row_weights(row)` returns the setup/late/early weights a
row declares, or None when the row does not say (NOT DETERMINABLE).

`compare_weights(a, b)` returns findings:
  - weights_not_recorded: a row declares none (never a silent pass).
  - weights_differ_not_comparable: both declare, a value differs.
  - calibration_weights_not_comparable: a calibration row (own setup weight
    that differs from the default) against any row with other weights.
Choice recorded in docs/WEIGHTS-AUDIT.md: new comparison rows use the default
50/1000/0.001 on both sides; calibration rows stay as they are, labelled
non-comparable with CG."""
from __future__ import annotations

from .anomaly import Finding

KEYS = ("setup", "late", "early")


def row_weights(row: dict) -> dict | None:
    w = row.get("weights")
    if w is None and isinstance(row.get("manifest"), dict):
        w = row["manifest"].get("weights")        # cg_trace rows seal it here
    if isinstance(w, dict) and all(k in w for k in ("setup", "late")):
        return {k: float(w[k]) for k in KEYS if k in w}
    cal = row.get("calibration")
    if isinstance(cal, dict) and "setup_weight" in cal:
        return {"setup": float(cal["setup_weight"]),
                "early": float(cal.get("holding_weight", 0.001)),
                "calibration": True}
    return None


def compare_weights(a: dict, b: dict) -> list[Finding]:
    wa, wb = row_weights(a), row_weights(b)
    out = []
    for name, w in (("first", wa), ("second", wb)):
        if w is None:
            out.append(Finding("weights_not_recorded",
                               f"{name} row declares no objective weights; "
                               "comparison undecidable, not a pass"))
    if wa is None or wb is None:
        return out
    diffs = {k: (wa[k], wb[k]) for k in KEYS
             if k in wa and k in wb
             and abs(wa[k] - wb[k]) > 1e-9 * max(1.0, abs(wa[k]))}
    if diffs:
        kind = ("calibration_weights_not_comparable"
                if wa.get("calibration") or wb.get("calibration")
                else "weights_differ_not_comparable")
        out.append(Finding(kind, f"weights differ {diffs}: a comparison "
                                 "would measure the weights"))
    return out


class ComparisonRefused(Exception):
    """A CG-vs-monolith comparison was refused by the weights guard."""


def verdict(findings: list) -> str:
    """The verdict as it appears in every comparison output, by name."""
    return ("weights_comparable" if not findings
            else ",".join(sorted({f.rule for f in findings})))


def require_comparable(a: dict, b: dict, where: str = "") -> str:
    """The comparison-path entry point. Returns the verdict string
    ('weights_comparable') or raises ComparisonRefused naming the findings.
    Every place that prints or files a CG-vs-monolith comparison calls this
    BEFORE it prints or files anything (tests/test_comparison_guard_wiring.py
    fails when such a file does not)."""
    f = compare_weights(a, b)
    if f:
        raise ComparisonRefused(f"{where}: {verdict(f)}: "
                                + "; ".join(x.detail for x in f))
    return verdict(f)
