"""Two-phase primal simplex with Bland's rule.

Source: Hillier & Lieberman, Introduction to Operations Research, 7th
ed., ch.4 (the simplex method): algebraic form, optimality test
(sec. 4.3), minimum ratio test, tie breaking and degeneracy (sec. 4.5,
citing Bland 1977), unbounded Z (no leaving variable, sec. 4.5), and
adapting to other model forms via artificial variables (sec. 4.6,
two-phase). Digital text, no OCR.

Solves: minimize c.x subject to A x (sense) b, x >= 0, where each row's
sense is "<=", ">=" or "==". Slack/surplus variables are added for
inequalities; artificial variables and a phase-1 objective handle ">="
and "==" rows (sec. 4.6).

Pivoting uses Bland's rule (entering: smallest index among negative
reduced costs; leaving: smallest index among minimum ratios), which
provably cannot cycle (Bland 1977, cited in sec. 4.5) - so termination
is guaranteed, not just hoped for.

Honesty: tested against brute-force vertex enumeration on random small
LPs; the Wyndor Glass Co. example (the book's running example) is
locked. Exact rational arithmetic (fractions.Fraction) - no float
tolerances anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import List, Optional


class LPStatus(str, Enum):
    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"


@dataclass(frozen=True)
class LPResult:
    status: LPStatus
    objective: Optional[Fraction]  # None unless OPTIMAL
    x: Optional[List[Fraction]]    # original variables only
    # Optimal-tableau snapshot for cut generation (Gomory): the final
    # tableau rows (row 0 = reduced costs, RHS in the last column),
    # the basic column per row, and the column layout. Populated on
    # OPTIMAL; None otherwise.
    tableau: Optional[List[List[Fraction]]] = None
    basis: Optional[List[int]] = None
    n_original: int = 0
    n_slack: int = 0


def solve_lp(c, A, b, senses) -> LPResult:
    """Minimize c.x s.t. A x <sense> b, x >= 0, by two-phase simplex."""
    m = len(A)
    n = len(c)
    if len(b) != m or len(senses) != m:
        raise ValueError("A, b, senses must have matching row counts")
    if m == 0:
        raise ValueError("at least one constraint")
    for row in A:
        if len(row) != n:
            raise ValueError("every row of A must have n entries")
    for s in senses:
        if s not in ("<=", ">=", "=="):
            raise ValueError(f"bad sense {s!r}")

    # Negative right-hand sides (sec. 4.6): multiply the row by -1 and
    # flip its sense, so the initial basic solution is feasible.
    A = [list(row) for row in A]
    b = list(b)
    senses = list(senses)
    for i in range(m):
        if Fraction(b[i]) < 0:
            A[i] = [-v for v in A[i]]
            b[i] = -b[i]
            if senses[i] == "<=":
                senses[i] = ">="
            elif senses[i] == ">=":
                senses[i] = "<="

    # Build the tableau in standard form. Columns: original vars, then
    # slack/surplus, then artificials. Rows: m constraint rows + row 0.
    cols = []
    for i in range(m):
        row = [Fraction(v) for v in A[i]]
        if senses[i] == "<=":
            row += [Fraction(1) if k == i else Fraction(0) for k in range(m)]
        elif senses[i] == ">=":
            row += [Fraction(-1) if k == i else Fraction(0) for k in range(m)]
        else:
            row += [Fraction(0)] * m
        cols.append(row)
    n_slack = m
    artificial_rows = [i for i in range(m) if senses[i] in (">=", "==")]
    n_art = len(artificial_rows)
    art_col = {}
    for k, i in enumerate(artificial_rows):
        cols[i] += [Fraction(1) if kk == k else Fraction(0) for kk in range(n_art)]
        art_col[i] = n + n_slack + k
    for i in range(m):
        if senses[i] == "<=":
            cols[i] += [Fraction(0)] * n_art
    total_vars = n + n_slack + n_art

    # basis[i] = variable index basic in row i. Slack columns start basic
    # for "<=" rows; for ">=" and "==" rows the artificial starts basic
    # (the surplus column is -I, not a valid basis column).
    basis = []
    for i in range(m):
        basis.append(n + i if senses[i] == "<=" else art_col[i])

    T = [[Fraction(0)] * (total_vars + 1) for _ in range(m + 1)]
    for i in range(m):
        for j in range(total_vars):
            T[i + 1][j] = cols[i][j]
        T[i + 1][total_vars] = Fraction(b[i])

    def set_objective(costs):
        # Row 0: reduced costs for a minimization objective.
        for j in range(total_vars):
            T[0][j] = Fraction(costs[j]) if j < len(costs) else Fraction(0)
        T[0][total_vars] = Fraction(0)
        # zero out basic columns: row0 -= cost[basic] * row_i
        for i in range(m):
            cb = Fraction(costs[basis[i]]) if basis[i] < len(costs) else Fraction(0)
            if cb != 0:
                for j in range(total_vars + 1):
                    T[0][j] -= cb * T[i + 1][j]

    def iterate() -> str:
        # Returns 'optimal', 'unbounded', or 'iterating'.
        while True:
            # Bland entering: smallest index with negative reduced cost.
            enter = -1
            for j in range(total_vars):
                if T[0][j] < 0:
                    enter = j
                    break
            if enter == -1:
                return "optimal"
            # Minimum ratio test; Bland leaving: smallest basic index on ties.
            best_ratio = None
            leave = -1
            for i in range(m):
                a = T[i + 1][enter]
                if a > 0:
                    ratio = T[i + 1][total_vars] / a
                    if best_ratio is None or ratio < best_ratio or (
                            ratio == best_ratio and basis[i] < basis[leave]):
                        best_ratio = ratio
                        leave = i
            if leave == -1:
                return "unbounded"
            # Pivot on (leave, enter).
            piv = T[leave + 1][enter]
            T[leave + 1] = [v / piv for v in T[leave + 1]]
            for r in range(m + 1):
                if r != leave + 1 and T[r][enter] != 0:
                    f = T[r][enter]
                    T[r] = [a - f * b for a, b in zip(T[r], T[leave + 1])]
            basis[leave] = enter

    # Phase 1: minimize the sum of artificials.
    costs1 = [Fraction(0)] * total_vars
    for j in art_col.values():
        costs1[j] = Fraction(1)
    set_objective(costs1)
    status = iterate()
    if status == "unbounded":
        # Phase-1 objective is bounded below by 0; cannot happen.
        raise AssertionError("phase 1 unbounded is impossible")
    # Row-0 RHS holds the negated phase-1 objective; feasible iff it is 0.
    if -T[0][total_vars] > 0:
        return LPResult(LPStatus.INFEASIBLE, None, None)

    # Phase 2: drive artificials out, then optimize the real objective.
    for i in range(m):
        if basis[i] in art_col.values():
            # Pivot the artificial out on any nonzero original/slack entry.
            for j in range(n + n_slack):
                if T[i + 1][j] != 0:
                    piv = T[i + 1][j]
                    T[i + 1] = [v / piv for v in T[i + 1]]
                    for r in range(m + 1):
                        if r != i + 1 and T[r][j] != 0:
                            f = T[r][j]
                            T[r] = [a - f * b2 for a, b2 in zip(T[r], T[i + 1])]
                    basis[i] = j
                    break
    costs2 = [Fraction(0)] * total_vars
    for j in range(n):
        costs2[j] = Fraction(c[j])
    # Artificial columns: keep them priced out with huge cost (they must
    # never re-enter); equivalently block them below in iterate2.
    set_objective(costs2)

    # Block artificial columns from entering by fixing their reduced
    # cost check: simplest correct approach - forbid in the entering scan.
    def iterate2() -> str:
        art_set = set(art_col.values())
        while True:
            enter = -1
            for j in range(total_vars):
                if j in art_set:
                    continue
                if T[0][j] < 0:
                    enter = j
                    break
            if enter == -1:
                return "optimal"
            best_ratio = None
            leave = -1
            for i in range(m):
                a = T[i + 1][enter]
                if a > 0:
                    ratio = T[i + 1][total_vars] / a
                    if best_ratio is None or ratio < best_ratio or (
                            ratio == best_ratio and basis[i] < basis[leave]):
                        best_ratio = ratio
                        leave = i
            if leave == -1:
                return "unbounded"
            piv = T[leave + 1][enter]
            T[leave + 1] = [v / piv for v in T[leave + 1]]
            for r in range(m + 1):
                if r != leave + 1 and T[r][enter] != 0:
                    f = T[r][enter]
                    T[r] = [a - f * b2 for a, b2 in zip(T[r], T[leave + 1])]
            basis[leave] = enter

    status = iterate2()
    if status == "unbounded":
        return LPResult(LPStatus.UNBOUNDED, None, None)
    x = [Fraction(0)] * n
    for i in range(m):
        if basis[i] < n:
            x[basis[i]] = T[i + 1][total_vars]
    snapshot_T = [list(row) for row in T]
    return LPResult(LPStatus.OPTIMAL, -T[0][total_vars], x,
                    tableau=snapshot_T, basis=list(basis),
                    n_original=n, n_slack=n_slack)
