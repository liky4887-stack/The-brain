"""The Species-Protection problem - the book's running LP example.

Source: Gusfield, Integer Linear Programming in Computational and
Systems Biology (Cambridge 2019; BCB tutorial Part I): the concrete
toy formulation (1)-(4) and its two "what-if" variants. Solved with
The-brain's exact rational simplex, so the optima are Fractions, not
floats.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Sequence

from ..lp import LPStatus, solve_lp

# The book's toy instance (regions A..E, species alpha/beta). The
# slide table's beta row and cost for E are typos; these coefficients
# are from the book's equations (2)-(3), which reproduce the book's
# stated optimal solution and objective exactly.
TOY_COSTS = [97, 73, 22, 11, 25]
TOY_ABUNDANCE = [[24, 36, 0, 15, 40], [83, 16, 19, 0, 18]]
TOY_TARGETS = [64, 87]


def species_protection(costs: Sequence, abundance: Sequence[Sequence],
                       targets: Sequence, extra: Sequence[tuple] = (),
                       maximize: Sequence | None = None) -> dict:
    """Minimize cost of preserving fractions of regions so every
    species meets its conservation target.

    costs: per-region cost of full preservation.
    abundance: abundance[s][r] = area of species s in region r.
    targets: conservation target per species.
    extra: additional (coeffs, sense, rhs) rows (for what-if
    questions, e.g. [([0,1,0,0,0], ">=", Fraction(1,10))] forces at
    least 10% of region B).
    maximize: optional coefficient vector; when given, maximize it
    subject to the same constraints plus `extra` (the book's first
    what-if: max X_B subject to cost <= 108.7).
    """
    n = len(costs)
    A = [list(row) for row in abundance]
    b = list(targets)
    senses = [">="] * len(A)
    for r in range(n):
        row = [0] * n
        row[r] = 1
        A.append(row)
        b.append(1)
        senses.append("<=")
    for coeffs, sense, rhs in extra:
        A.append(list(coeffs))
        b.append(rhs)
        senses.append(sense)
    if maximize is None:
        c = [Fraction(v) for v in costs]
    else:
        c = [-Fraction(v) for v in maximize]
    result = solve_lp(c, A, b, senses)
    if result.status is not LPStatus.OPTIMAL:
        return {"status": result.status.value, "objective": None, "x": None}
    obj = result.objective if maximize is None else -result.objective
    return {"status": "optimal", "objective": obj, "x": result.x}
