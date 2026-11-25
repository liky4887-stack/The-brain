"""Graph problems from computational biology as CP-SAT models.

Source: Gusfield, Integer Linear Programming in Computational and
Systems Biology (Cambridge 2019; BCB tutorial Parts II-III): maximum
clique (the book's first ILP formulation), near-cliques (allow k
missing edges, globally or per node), and maximum high-density
subgraphs with the P/E variable formulation.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from ortools.sat.python import cp_model

DENSITY_SCALE = 1000  # CP-SAT takes integer coefficients; d is scaled


def _solve(model: cp_model.CpModel, time_limit_s: float):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.solve(model)
    name = solver.status_name(status)
    if name not in ("OPTIMAL", "FEASIBLE"):
        return name, None
    return name, solver


def _edge_set(edges: Iterable[tuple[int, int]]) -> set[tuple[int, int]]:
    return {tuple(sorted(e)) for e in edges}


def max_clique(n: int, edges: Iterable[tuple[int, int]],
               weights: Optional[Sequence[int]] = None,
               time_limit_s: float = 30.0) -> dict:
    """Maximum(-weight) clique: C(i) + C(j) <= 1 for every non-edge
    (i, j) - the book's formulation (5). Nodes are 0..n-1."""
    E = _edge_set(edges)
    model = cp_model.CpModel()
    C = [model.new_bool_var(f"C{i}") for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) not in E:
                model.add(C[i] + C[j] <= 1)
    if weights is None:
        model.maximize(sum(C))
    else:
        if len(weights) != n:
            raise ValueError("weights must have length n")
        model.maximize(sum(w * c for w, c in zip(weights, C)))
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "size": None, "clique": None}
    clique = sorted(i for i in range(n) if solver.value(C[i]))
    size = (sum(weights[i] for i in clique) if weights is not None
            else len(clique))
    return {"status": status, "size": size, "clique": clique}


def max_near_clique(n: int, edges: Iterable[tuple[int, int]], k: int = 1,
                    per_node: bool = False,
                    time_limit_s: float = 30.0) -> dict:
    """Largest subset K that becomes a clique when up to k edges are
    added (near-clique, inequalities (8)-(9)). With per_node=True, up
    to k added edges PER NODE instead of globally (the book's
    generalization)."""
    E = _edge_set(edges)
    model = cp_model.CpModel()
    C = [model.new_bool_var(f"C{i}") for i in range(n)]
    V = {}
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) not in E:
                V[(i, j)] = model.new_bool_var(f"V{i}_{j}")
                model.add(C[i] + C[j] - V[(i, j)] <= 1)
    if per_node:
        for i in range(n):
            incident = [v for (a, b), v in V.items() if a == i or b == i]
            if incident:
                model.add(sum(incident) <= k)
    elif V:
        model.add(sum(V.values()) <= k)
    model.maximize(sum(C))
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "size": None, "clique": None}
    clique = sorted(i for i in range(n) if solver.value(C[i]))
    return {"status": status, "size": len(clique), "clique": clique}


def high_density_subgraph(n: int, edges: Iterable[tuple[int, int]],
                          d: float, time_limit_s: float = 30.0) -> dict:
    """Largest subgraph with density >= d (the P/E formulation,
    inequalities (11)-(14)). Density is compared exactly: the scaled
    constraint sum(E) * SCALE >= round(d * SCALE) * sum(P) is exact
    for d with at most three decimals."""
    E = _edge_set(edges)
    scaled = round(d * DENSITY_SCALE)
    if abs(d * DENSITY_SCALE - scaled) > 1e-9:
        raise ValueError("d must have at most 3 decimal places")
    model = cp_model.CpModel()
    C = [model.new_bool_var(f"C{i}") for i in range(n)]
    P, Ev = {}, {}
    for i in range(n):
        for j in range(i + 1, n):
            P[(i, j)] = model.new_bool_var(f"P{i}_{j}")
            model.add(C[i] + C[j] - P[(i, j)] <= 1)
            if (i, j) in E:
                Ev[(i, j)] = model.new_bool_var(f"E{i}_{j}")
                model.add(2 * Ev[(i, j)] - C[i] - C[j] <= 0)
    model.add(DENSITY_SCALE * sum(Ev.values()) - scaled * sum(P.values()) >= 0)
    model.add(sum(C) >= 1)  # exclude the vacuous empty subgraph
    model.maximize(sum(C))
    status, solver = _solve(model, time_limit_s)
    if solver is None:
        return {"status": status, "size": None, "subgraph": None}
    sub = sorted(i for i in range(n) if solver.value(C[i]))
    actual = sum(1 for (i, j) in E if i in sub and j in sub)
    possible = len(sub) * (len(sub) - 1) // 2
    return {"status": status, "size": len(sub), "subgraph": sub,
            "density": actual / possible if possible else 0.0}
