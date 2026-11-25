"""RNA secondary-structure prediction by ILP.

Source: Gusfield, Integer Linear Programming in Computational and
Systems Biology (Cambridge 2019; BCB tutorial Part V): the Simple RNA
Folding Problem as maximum nested complementary pairing (28)-(29),
with the stacked-quartet extension (30)-(31): Q(i,j) = 1 iff both
(i, j) and (i+1, j-1) are matched, so quartets can be counted or
weighted in the objective.
"""

from __future__ import annotations

from typing import Optional

from ortools.sat.python import cp_model

COMPLEMENTARY = {frozenset("AU"), frozenset("CG")}
DEFAULT_WEIGHTS = {"AU": 2, "UA": 2, "CG": 3, "GC": 3}  # hydrogen bonds


def _solve(model: cp_model.CpModel, time_limit_s: float):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.solve(model)
    name = solver.status_name(status)
    if name not in ("OPTIMAL", "FEASIBLE"):
        return name, None
    return name, solver


def rna_fold(seq: str, min_distance: int = 1,
             weighted: bool = False, stacking: bool = False,
             time_limit_s: float = 30.0) -> dict:
    """Most stable nested pairing of an RNA sequence.

    seq: string over {A, C, U, G}. Positions in the result are 0-based.
    min_distance: paired positions must satisfy j - i >= min_distance
    (the book's "minimum distance constraint to avoid impossible
    bends"; the book's base model has min_distance = 1).
    weighted: objective counts hydrogen bonds (AU=2, CG=3) instead of
    pairs (the book's "differential binding strengths").
    stacking: also create the quartet variables Q (30)-(31) and add
    the quartet count to the objective (the book's first stacking
    extension, max sum [P + Q]).
    """
    n = len(seq)
    if any(ch not in "ACUG" for ch in seq):
        raise ValueError("seq must be over {A, C, U, G}")
    model = cp_model.CpModel()
    P = {}
    for i in range(n):
        for j in range(i + min_distance, n):
            if j - i < min_distance:
                continue
            P[(i, j)] = model.new_bool_var(f"P{i}_{j}")
            if frozenset((seq[i], seq[j])) not in COMPLEMENTARY:
                model.add(P[(i, j)] == 0)  # only complementary pairs
    # each position in at most one pair (28)
    for j in range(n):
        terms = [P[(a, b)] for (a, b) in P if a == j or b == j]
        if terms:
            model.add(sum(terms) <= 1)
    # nesting (29): no crossing pairs i < i' < j < j'
    pairs = sorted(P)
    for a, (i, j) in enumerate(pairs):
        for (i2, j2) in pairs[a + 1:]:
            if i < i2 < j < j2:
                model.add(P[(i, j)] + P[(i2, j2)] <= 1)
    objective = []
    if weighted:
        objective = [DEFAULT_WEIGHTS.get(seq[i] + seq[j], 0) * p
                     for (i, j), p in P.items()]
    else:
        objective = list(P.values())
    Q = {}
    if stacking:
        for (i, j) in pairs:
            if (i + 1, j - 1) in P:
                Q[(i, j)] = model.new_bool_var(f"Q{i}_{j}")
                # (30) If-Then and (31) Only-If
                model.add(P[(i, j)] + P[(i + 1, j - 1)] - Q[(i, j)] <= 1)
                model.add(2 * Q[(i, j)] - P[(i, j)] - P[(i + 1, j - 1)] <= 0)
        objective += list(Q.values())
    if not objective:
        return {"status": "OPTIMAL", "pairs": [], "quartets": [],
                "matched": 0}
    model.maximize(sum(objective))
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "pairs": None, "quartets": None,
                "matched": None}
    chosen = sorted(e for e, p in P.items() if solver.value(p))
    quartets = sorted(e for e, q in Q.items() if solver.value(q))
    return {"status": status, "pairs": chosen, "quartets": quartets,
            "matched": len(chosen)}
