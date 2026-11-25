"""Uncapacitated lot-sizing (ULS): the Wagner-Whitin dynamic program.

Source: Wolsey, Integer Programming, 2nd ed., sec. 5.2 (forward recursion,
Observation 5.4 cost transformation, Example 5.1) - digital text, no OCR.

Problem: periods t = 1..n with demands d_t >= 0, unit production costs
p_t, unit holding costs h_t, setup costs f_t >= 0. Choose production y_t
and setups x_t to satisfy every demand at minimum total cost
sum_t (p_t y_t + h_t s_t + f_t x_t), where s_t is end-of-period stock.

Structure used (Wolsey Proposition 5.1): an optimal plan exists where
production in t happens only with zero entering stock, and then covers
demand for an exact run of periods t..t+k. So the only real choice is the
set of production periods, and the forward recursion

    H(k) = min over 1 <= t <= k of  H(t-1) + f_t + c_t * (d_t + ... + d_k)

with H(0) = 0 and c_t = p_t + sum_{i >= t} h_i (Observation 5.4: the
constant sum_t h_t * d_1t is added back at the end) solves ULS in O(n^2).

Honesty rules: the reported cost is recomputed from the returned plan in
the ORIGINAL (p, h, f) costs, never from the transformed c-costs. Tests
validate against brute-force enumeration of all 2^n setup sets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence


@dataclass(frozen=True)
class ULSPlan:
    production: List[float]  # y_t
    setups: List[int]        # x_t
    stocks: List[float]      # s_t (end of period)


def _validate(d, p, h, f):
    n = len(d)
    if not (len(p) == len(h) == len(f) == n):
        raise ValueError("d, p, h, f must have equal length")
    if n == 0:
        raise ValueError("at least one period")
    if any(v < 0 for v in d):
        raise ValueError("demands must be nonnegative")
    if any(v < 0 for v in f):
        raise ValueError("setup costs must be nonnegative")


def solve_uls(d: Sequence[float], p: Sequence[float],
              h: Sequence[float], f: Sequence[float]) -> ULSPlan:
    """Optimal ULS plan via the forward recursion, O(n^2)."""
    _validate(d, p, h, f)
    n = len(d)
    # c_t = p_t + sum_{i >= t} h_i (0-based index t means period t+1).
    c = [p[t] + sum(h[t:]) for t in range(n)]
    # demand_sum[t][k] = d_t + ... + d_k for t <= k.
    demand_sum = [[0.0] * n for _ in range(n)]
    for t in range(n):
        acc = 0.0
        for k in range(t, n):
            acc += d[k]
            demand_sum[t][k] = acc

    H = [0.0] * (n + 1)          # H[k] = best cost for periods 1..k
    last_prod = [0] * (n + 1)    # argmin t achieving H[k]; 0 = no production
    for k in range(1, n + 1):
        if d[k - 1] == 0:
            # No demand in period k: nothing new to produce, and any
            # production in k would only serve later periods. (The plain
            # recursion would force a pointless setup when d_tk = 0.)
            H[k] = H[k - 1]
            last_prod[k] = 0
            continue
        best = None
        best_t = k
        for t in range(1, k + 1):
            val = H[t - 1] + f[t - 1] + c[t - 1] * demand_sum[t - 1][k - 1]
            if best is None or val < best:
                best = val
                best_t = t
        H[k] = best
        last_prod[k] = best_t

    production = [0.0] * n
    setups = [0] * n
    k = n
    while k > 0:
        t = last_prod[k]
        if t == 0:
            k -= 1
            continue
        production[t - 1] = demand_sum[t - 1][k - 1]
        setups[t - 1] = 1
        k = t - 1
    stocks = [0.0] * n
    for t in range(n):
        stocks[t] = (stocks[t - 1] if t > 0 else 0.0) + production[t] - d[t]
    return ULSPlan(production=production, setups=setups, stocks=stocks)


def plan_cost(plan: ULSPlan, d: Sequence[float], p: Sequence[float],
              h: Sequence[float], f: Sequence[float]) -> float:
    """Total cost of a plan in the original (p, h, f) costs. Checks feasibility."""
    _validate(d, p, h, f)
    n = len(d)
    for t in range(n):
        expected = (plan.stocks[t - 1] if t > 0 else 0.0) + plan.production[t] - d[t]
        if abs(plan.stocks[t] - expected) > 1e-6:
            raise ValueError(f"plan violates balance in period {t + 1}")
        if plan.stocks[t] < -1e-9:
            raise ValueError(f"plan has negative stock in period {t + 1}")
        if plan.production[t] > 1e-9 and plan.setups[t] != 1:
            raise ValueError(f"production without setup in period {t + 1}")
    return sum(
        p[t] * plan.production[t] + h[t] * plan.stocks[t] + f[t] * plan.setups[t]
        for t in range(n)
    )
