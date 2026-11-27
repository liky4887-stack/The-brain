"""Pool-level lower bound on the model's lateness term, from RAW records
only (guards.independent_data), independent of the model code.

LP over per-(SKU, day) production q, minimising the cumulative shortfall
sum_{s,t} max(0, cum_demand(s,t) - cum_q(s,t)) (= backlog_unit_days):
  - supplier pool: per (material, day), sum_s recipe[s][r] * q_{s,t} <= cap
  - labor pool: per day, sum_s q_{s,t} / rate_s <= labor_cap(t)
  - plant minutes: per plant and day, sum_{s in plant} q_{s,t}/rate_s <=
    n_lines * minutes_per_line_day (default: the model's cap_eff, i.e.
    capacity net of the changeover allowance)
ASSUMPTIONS (a violation of any makes the bound invalid, not the plan):
  build-ahead (early production) allowed; no setups, no changeover time
  beyond the allowance already in minutes_per_line_day; no minimum lot;
  demand outside the window ignored (as the model does); pools are those
  passed in (the same caps the plan was built for).
INITIAL INVENTORY: it lowers the true need, so ignoring it would make the
bound too HIGH (invalid). The caller must pass `inv0s` (one dict sku ->
units per plant, or {} / None per plant for "none") explicitly; stock is
applied as target = cum_demand - inv0. Min-lot, setups, line-down days
and extra costs only RAISE the true optimum, so they keep the bound valid.
Every plan feasible for the model has backlog_unit_days >= this bound, so
a record claiming less is physically impossible or mis-measured."""
from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

from .independent_data import raw_due_day, raw_recipe_data, raw_sku_data


def lateness_lower_bound(factories, horizon_start, days, minutes_per_line_day,
                         supplier_cap=None, labor_cap=None, *, inv0s):
    """Returns min backlog_unit_days (shortfall unit-days). `inv0s` is
    REQUIRED (keyword): a list aligned with factories of {sku: units} (or
    None for "no stock"); omitting it is a TypeError, never a silent
    no-inventory assumption."""
    if inv0s is None or len(inv0s) != len(factories):
        raise ValueError("inv0s must be a list aligned with factories")
    supplier_cap = supplier_cap or {}
    labor_cap = labor_cap or {}
    skus = []
    for pi, f in enumerate(factories):
        sk = raw_sku_data(f)
        rc = raw_recipe_data(f)
        dem: dict = {}
        for d in f.demands:
            t = raw_due_day(d.due, horizon_start)
            if 0 <= t < days:
                dem.setdefault(d.item, [0.0] * days)[t] += d.quantity
        lines = {l for s in sk.values() for l in s[1]}
        for s, ds in dem.items():
            skus.append((pi, s, sk[s][0], rc.get(s, {}), ds, len(lines),
                     (inv0s[pi] or {}).get(s, 0.0)))
    n = len(skus)
    if n == 0:
        return 0.0
    nq = n * days
    nv = 2 * nq
    qi = lambda i, t: i * days + t       # noqa: E731
    si = lambda i, t: nq + i * days + t  # noqa: E731
    A, b = [], []
    for i, (_pi, _s, _r, _rc, ds, _nl, inv) in enumerate(skus):
        cum = -inv
        for t in range(days):
            cum += ds[t]
            row = np.zeros(nv)
            for tau in range(t + 1):
                row[qi(i, tau)] -= 1.0
            row[si(i, t)] = -1.0
            A.append(row)
            b.append(-cum)
    for (r, t), cap in supplier_cap.items():
        row = np.zeros(nv)
        for i, (_pi, _s, _rate, rc, _ds, _nl, _inv) in enumerate(skus):
            if rc.get(r):
                row[qi(i, t)] = rc[r]
        if row.any():
            A.append(row)
            b.append(cap)
    for t, cap in labor_cap.items():
        row = np.zeros(nv)
        for i, (_pi, _s, rate, _rc, _ds, _nl, _inv) in enumerate(skus):
            row[qi(i, t)] = 1.0 / rate
        A.append(row)
        b.append(cap)
    for pi in range(len(factories)):
        nl = next((x[5] for x in skus if x[0] == pi), 0)
        for t in range(days):
            row = np.zeros(nv)
            for i, (p2, _s, rate, _rc, _ds, _nl, _inv) in enumerate(skus):
                if p2 == pi:
                    row[qi(i, t)] = 1.0 / rate
            if row.any():
                A.append(row)
                b.append(nl * minutes_per_line_day)
    c = np.zeros(nv)
    c[nq:] = 1.0
    r = linprog(c, A_ub=np.array(A), b_ub=b, bounds=(0, None),
                method="highs")
    if r.status != 0:
        raise RuntimeError(f"physical bound LP status {r.status}")
    return float(r.fun)
