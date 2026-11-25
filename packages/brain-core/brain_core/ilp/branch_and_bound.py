"""Branch-and-bound for integer linear programs.

Source: Fischetti, Introduction to Mathematical Optimization (5th ed.
2019), sec. 6.4: branching on a fractional variable (xh <= floor or
xh >= ceil), the three fathoming criteria (integer relaxation,
infeasible relaxation, bounding LB >= incumbent), the integer-cost
strengthening LB = ceil(c.x*) when c is integer, branching-variable
choice (fractional part nearest 0.5), and the two node-selection
strategies (depth-first, best-bound first). Relaxations are solved
with The-brain's exact rational simplex, so every bound is exact.
"""

from __future__ import annotations

from fractions import Fraction
from math import floor, ceil
from typing import List, Optional, Sequence, Tuple

from ..lp import LPStatus, solve_lp


def solve_ilp_bb(c: Sequence, A: Sequence[Sequence], b: Sequence,
                 senses: Sequence[str],
                 strategy: str = "best-bound",
                 max_nodes: int = 10_000) -> dict:
    """Minimize c.x s.t. A x <sense> b, x >= 0 integer.

    strategy: "best-bound" (most promising node first) or "dfs"
    (deepest node first). Returns status ("optimal", "infeasible",
    "node_limit"), objective, x, and nodes explored."""
    if strategy not in ("best-bound", "dfs"):
        raise ValueError("strategy must be 'best-bound' or 'dfs'")
    n = len(c)
    c = [Fraction(v) for v in c]
    A = [list(map(Fraction, row)) for row in A]
    b = [Fraction(v) for v in b]
    senses = list(senses)
    c_integer = all(v.denominator == 1 for v in c)

    incumbent_x: Optional[List[Fraction]] = None
    incumbent_z: Optional[Fraction] = None
    # open nodes: (lower bound, sequence number, bounds added)
    # bounds added: list of (var_index, "<=" or ">=", value)
    open_nodes: List[Tuple[Fraction, int, list]] = []
    counter = 0
    open_nodes.append((Fraction(0), counter, []))
    nodes_explored = 0

    while open_nodes:
        if strategy == "best-bound":
            pos = min(range(len(open_nodes)), key=lambda i: open_nodes[i][0])
        else:
            pos = len(open_nodes) - 1
        _, _, bounds = open_nodes.pop(pos)
        # node relaxation = base system + branching bounds
        A_n = [list(row) for row in A]
        b_n = list(b)
        s_n = list(senses)
        for j, sense, val in bounds:
            row = [Fraction(0)] * n
            row[j] = Fraction(1)
            A_n.append(row)
            b_n.append(val)
            s_n.append(sense)
        r = solve_lp(c, A_n, b_n, s_n)
        nodes_explored += 1
        if nodes_explored > max_nodes:
            return {"status": "node_limit", "objective": None,
                    "x": incumbent_x, "incumbent": incumbent_z,
                    "nodes": nodes_explored}
        if r.status is LPStatus.INFEASIBLE:
            continue  # fathoming criterion 2
        if r.status is LPStatus.UNBOUNDED:
            return {"status": "unbounded", "objective": None, "x": None,
                    "incumbent": incumbent_z, "nodes": nodes_explored}
        lb = r.objective
        if c_integer:
            lb = Fraction(ceil(lb))  # sec. 6.4.1 strengthening
        if incumbent_z is not None and lb >= incumbent_z:
            continue  # fathoming criterion 3 (bounding)
        x = r.x
        frac = [(v - floor(v)) for v in x]
        if all(f == 0 for f in frac):
            incumbent_x, incumbent_z = x, r.objective  # criterion 1
            continue
        # branching variable: fractional part nearest 0.5 (sec. 6.4.2)
        h = min(range(n), key=lambda j: abs(frac[j] - Fraction(1, 2)))
        low = (h, "<=", Fraction(floor(x[h])))
        high = (h, ">=", Fraction(ceil(x[h])))
        for child in (low, high):
            counter += 1
            open_nodes.append((lb, counter, bounds + [child]))

    if incumbent_x is None:
        return {"status": "infeasible", "objective": None, "x": None,
                "incumbent": None, "nodes": nodes_explored}
    return {"status": "optimal", "objective": incumbent_z,
            "x": incumbent_x, "incumbent": incumbent_z,
            "nodes": nodes_explored}
