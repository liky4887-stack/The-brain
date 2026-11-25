"""MILP neighbourhood search over the bucket model (Stage 4, slice 2).

Large-neighbourhood search on the level-1 bucket MILP: from an
incumbent BucketResult, fix MOST SKUs to their incumbent production
(their x and y variables pinned), re-solve the small free remainder
with a short time limit, and accept only a measured improvement.
Repeat for a bounded number of iterations inside a wall budget.

Honesty rules honored:
- every objective is recomputed from the returned x over the FULL
  variable set (fixed + free contribute together), never trusted
  from solver internals; the incumbent's own objective comes from
  solve_buckets, which recomputes it the same way;
- "improved" means strictly better by EPS on that recomputed number;
  a run that finds nothing reports the incumbent unchanged - never
  a claimed improvement that was not measured;
- an incumbent without an objective (unsolved/infeasible) is refused.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import numpy as np

from ..records.models import Factory
from ..rolling.two_level import (BucketResult, DEFAULT_CHG_ALLOWANCE,
                                 DEFAULT_WEIGHTS, ObjectiveWeights,
                                 build_bucket_mip)
from ..solvers.highs_mip import solve_mip

EPS = 1e-6


@dataclass
class LNSResult:
    bucket: BucketResult
    improved: bool
    start_objective: float
    objective: float                  # recomputed, of the returned plan
    iterations_run: int
    accepted: int
    wall_s: float
    history: list[dict] = field(default_factory=list)


def _incumbent_vectors(maps: dict, incumbent: BucketResult,
                       n_vars: int) -> tuple[np.ndarray, np.ndarray]:
    """Incumbent x (production) and y (setup) values, reconstructed
    from the returned quantities - the same numbers the plan carries,
    not solver internals."""
    x = np.zeros(n_vars)
    for (s, t, l), q in incumbent.qty.items():
        x[maps["x"][(s, t, l)]] = q
    y = np.zeros(n_vars)
    for (s, t), j in maps["y"].items():
        y[j] = 1.0 if any((s, t, l) in incumbent.qty
                          for l in maps["sku"][s][1]) else 0.0
    return x, y


def lns_improve(factory: Factory, horizon_start, days: int,
                cap_min: float, incumbent: BucketResult,
                chg_allowance: float = DEFAULT_CHG_ALLOWANCE,
                weights: ObjectiveWeights = DEFAULT_WEIGHTS,
                inv0: dict | None = None,
                extra_due_day0: dict | None = None,
                cap_override: dict | None = None,
                iterations: int = 3, free_fraction: float = 0.3,
                neigh_time_s: float = 15.0,
                wall_budget_s: float = 120.0,
                seed: int = 0) -> LNSResult:
    """Improve (or return unchanged) an incumbent bucket plan by LNS."""
    t0 = time.monotonic()
    if incumbent.objective is None or not incumbent.qty:
        return LNSResult(incumbent, False,
                         incumbent.objective or 0.0,
                         incumbent.objective or 0.0,
                         0, 0, time.monotonic() - t0,
                         [{"note": "no incumbent objective; refused"}])
    mip, maps = build_bucket_mip(factory, horizon_start, days, cap_min,
                                 chg_allowance, inv0, extra_due_day0,
                                 cap_override, weights)
    n_vars = len(mip.c)
    best_x, best_y = _incumbent_vectors(maps, incumbent, n_vars)
    best_obj = float(incumbent.objective)
    active = maps["active"]
    rng = random.Random(seed)
    history: list[dict] = []
    accepted = 0
    run = 0
    for it in range(iterations):
        if time.monotonic() - t0 > wall_budget_s:
            history.append({"iteration": it, "note": "wall budget"})
            break
        run += 1
        k = max(1, round(free_fraction * len(active)))
        free = set(rng.sample(active, k))
        lb = mip.lb.copy()
        ub = mip.ub.copy()
        for (s, t, l), j in maps["x"].items():
            if s not in free:
                lb[j] = ub[j] = best_x[maps["x"][(s, t, l)]]
        for (s, t), j in maps["y"].items():
            if s not in free:
                lb[j] = ub[j] = best_y[j]
        from ..solvers.highs_mip import MIP
        sub = MIP(mip.name + ":lns", mip.c, mip.A, mip.sense,
                  mip.rhs, lb, ub, mip.integrality)
        res = solve_mip(sub, time_limit_s=neigh_time_s,
                        mip_rel_gap=0.0)
        if res["x"] is None:
            history.append({"iteration": it, "accepted": False,
                            "note": str(res["status"])})
            continue
        obj = float(mip.c @ res["x"])   # full-variable recompute
        ok = obj < best_obj - EPS
        if ok:
            accepted += 1
            best_obj = obj
            best_x = res["x"].copy()
            for (s, t), j in maps["y"].items():
                best_y[j] = res["x"][j]
        history.append({"iteration": it, "objective": obj,
                        "accepted": ok})
    qty = {k: float(best_x[j]) for k, j in maps["x"].items()
           if best_x[j] > 1e-6}
    bucket = BucketResult(incumbent.status, best_obj, None, qty,
                          incumbent.skipped_future_demands,
                          incumbent.n_binaries, incumbent.n_vars)
    return LNSResult(bucket, accepted > 0, float(incumbent.objective),
                     best_obj, run, accepted,
                     time.monotonic() - t0, history)
