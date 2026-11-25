"""Gomory's fractional cutting-plane algorithm.

Source: Fischetti, Introduction to Mathematical Optimization (5th ed.
2019), sec. 6.3: from a row t of the optimal tableau whose basic
variable xh is fractional (6.2), Chvatal truncation gives the integer
form (6.3); subtracting it from the row gives the fractional form
(6.4): sum_{j in F} phi(a_tj) x_j >= phi(b_t), phi(r) = r - floor(r).
The cut is valid for every integer solution (all coefficients >= 0)
and violated by the current fractional optimum (LHS = 0 there).

The whole computation runs in exact rational arithmetic. We keep the
working LP in equality form (one slack/surplus variable per row,
added by us), so each cut (6.4) is appended with its own surplus
variable and the column space grows by one per cut. The book's
implementation reoptimizes with the dual simplex; re-solving with the
exact two-phase simplex yields the same optima.
"""

from __future__ import annotations

from fractions import Fraction
from typing import List, Sequence

from ..lp import LPStatus, solve_lp


def _frac(r: Fraction) -> Fraction:
    return r - r.numerator // r.denominator


def solve_ilp_gomory(c: Sequence, A: Sequence[Sequence], b: Sequence,
                     senses: Sequence[str], max_cuts: int = 200) -> dict:
    """Minimize c.x s.t. A x <sense> b, x >= 0 integer (pure-integer
    problem with integer data), by Gomory's cutting-plane algorithm.

    Returns status ("optimal", "infeasible", "unbounded",
    "cut_limit", "no_generating_row"), objective, x (original
    variables), and the generated cuts in fractional form (6.4)."""
    n = len(c)
    m0 = len(A)
    # equality form: one slack/surplus per original row
    rows: List[List[Fraction]] = []
    for i in range(m0):
        row = [Fraction(v) for v in A[i]]
        row += [Fraction(1) if k == i else Fraction(0) for k in range(m0)]
        if senses[i] == ">=":
            row[n + i] = Fraction(-1)
        elif senses[i] == "==":
            row[n + i] = Fraction(0)  # keep the column for uniform width
        rows.append(row)
    b_eq = [Fraction(v) for v in b]
    W = n + m0
    c_ext = [Fraction(v) for v in c] + [Fraction(0)] * (W - n)
    cuts: List[dict] = []
    for _ in range(max_cuts):
        r = solve_lp(c_ext, rows, b_eq, ["=="] * len(rows))
        if r.status is not LPStatus.OPTIMAL:
            return {"status": r.status.value, "objective": None,
                    "x": None, "cuts": cuts}
        x = r.x[:n]
        if all(v.denominator == 1 for v in x):
            return {"status": "optimal", "objective": r.objective,
                    "x": x, "cuts": cuts}
        # generating row: basic structural variable, fractional RHS (6.2)
        T, basis = r.tableau, r.basis
        rhs_col = len(T[0]) - 1
        basic = set(basis)
        gen = None
        for i, bv in enumerate(basis):
            if bv < W and T[i + 1][rhs_col].denominator != 1:
                gen = i
                break
        if gen is None:
            return {"status": "no_generating_row", "objective": None,
                    "x": None, "cuts": cuts}
        row = T[gen + 1]
        # fractional form (6.4) over non-basic structural columns
        cut = [Fraction(0)] * W
        for j in range(W):
            if j not in basic and row[j] != 0:
                cut[j] = _frac(row[j])
        rhs = _frac(row[rhs_col])
        cuts.append({"coeffs": cut, "rhs": rhs})
        # append cut with its own surplus: cut.x - s = rhs
        for old in rows:
            old.append(Fraction(0))
        rows.append(cut + [Fraction(-1)])
        b_eq.append(rhs)
        c_ext.append(Fraction(0))
        W += 1
    return {"status": "cut_limit", "objective": None, "x": None,
            "cuts": cuts}
