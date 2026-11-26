"""Independent min-lot check for a plan.

Does not use the MIP rows, big-M values or the `lots` dict the model was
built with. It recomputes the lot from the instance data alone:
L = minlot_days x daily demand of the sku (median demand when the sku has
none). A plant/sku/day that produces anything (> 1e-6 total over lines)
must produce at least L. The model caps L at 0.9 x its big-M; that cap is
NOT applied here (stricter), so any cap-induced shortfall is reported as
a violation instead of being hidden.
"""
from __future__ import annotations


def independent_min_lot(qtys, dd, d_med, minlot_days, tol=1e-6):
    """qtys: per plant dict (sku, day, line) -> qty. dd: (plant, sku) ->
    daily demand. Returns dict with the count, worst shortfall ratio and
    the first 5 violations."""
    viol, runs = [], 0
    for p_i, qd in enumerate(qtys):
        by = {}
        for (sk, t, _l), q in qd.items():
            by[(sk, t)] = by.get((sk, t), 0.0) + q
        for (sk, t), q in by.items():
            if q <= tol:
                continue
            runs += 1
            lot = minlot_days * dd.get((p_i, sk), d_med)
            if q < lot * (1 - 1e-6) - tol:
                viol.append((p_i, sk, t, q, lot))
    worst = max((1 - q / lot for _, _, _, q, lot in viol), default=0.0)
    return {"runs": runs, "violations": len(viol),
            "worst_shortfall_frac": worst,
            "first": [list(v) for v in viol[:5]]}
