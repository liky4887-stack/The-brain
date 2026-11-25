"""Uncapacitated lot-sizing with backlogging (ULS-B).

Source: Bynum, Hackebeil, Hart, Laird, Nicholson, Siirola, Watson,
Woodruff, "Pyomo - Optimization Modeling in Python", 3rd ed. (Springer
open access, 2020), sec. 8.6, formulation LS.1-LS.6 and Table 8.1.
Digital text, no OCR.

Problem: periods 1..n with demands d_t >= 0, setup cost f >= 0, unit
production cost p >= 0, holding cost h_plus >= 0 per unit-period,
shortage (backlog) cost h_minus >= 0 per unit-period, production
capacity per setup P (big-M; default unbounded), initial inventory
i0_pos >= 0 and initial backlog i0_neg >= 0. Minimize

    sum_t ( f y_t + p x_t + h_plus I+_t + h_minus I-_t )

s.t.  I_t = I_{t-1} + x_t - d_t,   I_t = I+_t - I-_t,   x_t <= P y_t.

Structure used (the Wolsey ch.5 interval argument extended to
backlogging): an optimal plan exists that partitions the horizon into
intervals [s..e]; within one interval all demand is produced in a
single period t* in [s..e], with demands of periods s..t*-1 backlogged
to t* and demands of t*+1..e held from t*. So

    H(e) = min over 1 <= s <= e, s <= t* <= e of
        H(s-1) + f + p*D + h_minus * BL(s,t*) + h_plus * HD(t*,e)

with D = d_s + ... + d_e, BL(s,t*) = sum_{j=s}^{t*-1} (t*-j) d_j and
HD(t*,e) = sum_{j=t*+1}^{e} (j-t*) d_j. O(n^3).

Honesty rules: the reported cost is recomputed from the returned plan
in the original costs (plan_cost), never from DP internals. Tests
cross-validate against an independent CP-SAT model of LS.1-LS.6 and
lock the book's Table 8.1 instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence


@dataclass(frozen=True)
class ULSBPlan:
    production: List[float]   # x_t
    setups: List[int]         # y_t
    inv_pos: List[float]      # I+_t (end of period, after demand)
    inv_neg: List[float]      # I-_t (end of period)


def solve_uls_backlog(d: Sequence[float], f: float, p: float = 0.0,
                      h_plus: float = 1.0, h_minus: float = 1.0,
                      capacity: Optional[float] = None,
                      i0_pos: float = 0.0, i0_neg: float = 0.0) -> ULSBPlan:
    """Exact DP for the UNCAPACITATED case (capacity=None). With a
    capacity, setup costs make the problem NP-hard (capacitated lot
    sizing); use solve_uls_backlog_cpsat instead, which is honest about
    its status."""
    n = len(d)
    if n == 0:
        raise ValueError("at least one period")
    if any(v < 0 for v in d):
        raise ValueError("demands must be nonnegative")
    if min(f, p, h_plus, h_minus, i0_pos, i0_neg) < 0:
        raise ValueError("costs and initial levels must be nonnegative")
    if capacity is not None:
        raise NotImplementedError(
            "capacitated ULS-B with setups is NP-hard; "
            "use solve_uls_backlog_cpsat")
    d_orig = list(d)
    # initial stock/backlog nets against the earliest demands
    d = list(d)
    stock = i0_pos - i0_neg
    for t in range(n):
        if stock > 0:
            take = min(d[t], stock)
            d[t] -= take
            stock -= take
        elif stock < 0:
            d[t] += -stock
            stock = 0.0

    # prefix sums of d and of j*d_j for O(1) interval quantities
    S = [0.0] * (n + 1)      # S[k] = d_1 + ... + d_k
    W = [0.0] * (n + 1)      # W[k] = 1*d_1 + ... + k*d_k
    for k in range(1, n + 1):
        S[k] = S[k - 1] + d[k - 1]
        W[k] = W[k - 1] + k * d[k - 1]

    def backlog_cost(s: int, t: int) -> float:
        # sum_{j=s}^{t-1} (t - j) d_j  (1-based, s <= t)
        return t * (S[t - 1] - S[s - 1]) - (W[t - 1] - W[s - 1])

    def holding_cost(t: int, e: int) -> float:
        # sum_{j=t+1}^{e} (j - t) d_j  (1-based, t <= e)
        return (W[e] - W[t]) - t * (S[e] - S[t])

    H = [0.0] * (n + 1)
    choice = [(0, 0)] * (n + 1)  # (s, t*) achieving H[e]
    for e in range(1, n + 1):
        best = None
        for s in range(1, e + 1):
            for t in range(s, e + 1):
                qty = S[e] - S[s - 1]
                val = (H[s - 1] + f + p * qty
                       + h_minus * backlog_cost(s, t)
                       + h_plus * holding_cost(t, e))
                if best is None or val < best - 1e-12:
                    best = val
                    choice[e] = (s, t)
        H[e] = best

    # the book's model (LS.1-LS.6) charges terminal backlog only once:
    # demands of a final suffix may stay unproduced at h_minus per
    # unit-period until the horizon end. Answer = min over k of
    # H(k) + terminal backlog of k+1..n.
    terminal = [0.0] * (n + 1)  # terminal[k] = backlog cost of k+1..n
    for k in range(n - 1, -1, -1):
        terminal[k] = terminal[k + 1] + h_minus * (n - k) * d[k]
    k_end = min(range(n + 1), key=lambda k: H[k] + terminal[k])

    # unroll the intervals up to k_end
    production = [0.0] * n
    setups = [0] * n
    e = k_end
    while e > 0:
        s, t = choice[e]
        production[t - 1] += S[e] - S[s - 1]
        setups[t - 1] = 1
        e = s - 1
    inv_pos, inv_neg = _levels(production, d_orig, i0_pos, i0_neg)
    return ULSBPlan(production, setups, inv_pos, inv_neg)


def _levels(production: List[float], d: List[float],
            i0_pos: float, i0_neg: float):
    inv = i0_pos - i0_neg
    inv_pos, inv_neg = [], []
    for t in range(len(d)):
        inv += production[t] - d[t]
        inv_pos.append(max(inv, 0.0))
        inv_neg.append(max(-inv, 0.0))
    return inv_pos, inv_neg


def plan_cost(plan: ULSBPlan, d: Sequence[float], f: float, p: float,
              h_plus: float, h_minus: float) -> float:
    """Cost recomputed from the returned plan in original costs."""
    return (f * sum(plan.setups) + p * sum(plan.production)
            + h_plus * sum(plan.inv_pos) + h_minus * sum(plan.inv_neg))


def solve_uls_backlog_cpsat(d: Sequence[float], f: float, p: float = 0.0,
                            h_plus: float = 1.0, h_minus: float = 1.0,
                            capacity: Optional[float] = None,
                            i0_pos: float = 0.0, i0_neg: float = 0.0,
                            scale: int = 1000,
                            time_limit_s: float = 30.0) -> dict:
    """Capacitated or uncapacitated ULS-B through CP-SAT (the book's
    LS.1-LS.6 with x_t <= P y_t). Floats are scaled to integers
    (CP-SAT is integer-only). Returns the plan, its status exactly as
    the solver reported it, and the cost RECOMPUTED from the plan by
    plan_cost."""
    from ortools.sat.python import cp_model
    n = len(d)
    if n == 0:
        raise ValueError("at least one period")
    ds = [round(v * scale) for v in d]
    big = sum(ds) + max(round(i0_pos * scale), 1) + 1
    m = cp_model.CpModel()
    x = [m.new_int_var(0, big, f"x{t}") for t in range(n)]
    y = [m.new_bool_var(f"y{t}") for t in range(n)]
    ip = [m.new_int_var(0, big, f"ip{t}") for t in range(n)]
    im = [m.new_int_var(0, big, f"im{t}") for t in range(n)]
    cap = round(capacity * scale) if capacity is not None else big
    for t in range(n):
        prev = (round(i0_pos * scale) - round(i0_neg * scale)) if t == 0             else ip[t - 1] - im[t - 1]
        m.add(ip[t] - im[t] == prev + x[t] - ds[t])
        m.add(x[t] <= cap * y[t])
    # quantities are scaled by `scale`, so to keep the true cost ratios
    # the per-unit coefficients scale by `scale` and the per-setup
    # coefficient (no quantity) by scale**2
    m.minimize(round(f * scale * scale) * sum(y)
               + round(p * scale) * sum(x)
               + round(h_plus * scale) * sum(ip)
               + round(h_minus * scale) * sum(im))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.status_name(solver.solve(m))
    if status not in ("OPTIMAL", "FEASIBLE"):
        return {"status": status, "plan": None, "cost": None}
    plan = ULSBPlan(
        production=[solver.value(v) / scale for v in x],
        setups=[solver.value(v) for v in y],
        inv_pos=[solver.value(v) / scale for v in ip],
        inv_neg=[solver.value(v) / scale for v in im])
    return {"status": status, "plan": plan,
            "cost": plan_cost(plan, d, f, p, h_plus, h_minus)}
