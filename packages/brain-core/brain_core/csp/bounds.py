"""Bounds-consistent domain reduction for linear constraints on integer
intervals, and MAC search (Apt, Principles of Constraint Programming,
2003, ch. 6.4 and ch. 8).

Source: digital text, no OCR. Implements the LINEAR INEQUALITY 1 rule
(sec. 6.4.1) and the LINEAR EQUALITY rule (sec. 6.4.2, built from the
two inequality directions), applied to a fixpoint, and the backtracking
search with constraint propagation (sec. 8.6.3, MAC: propagate after
every assignment).

Exactness: all bound arithmetic uses Fraction (integers exactly); the
integer tightening is floor/ceil of exact rationals, as the rules
state. A constraint whose domain interval becomes empty is a FAILURE
(Apt's term) - reported, never hidden.

Locked book example (Fig. 6.3-6.4): <3x - 5y = 4; x in [0..9], y in
[1..8]> stabilises at x in [3..8], y in [1..4].
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import ceil, floor
from typing import Dict, List, Optional, Tuple

Domain = Tuple[int, int]  # [l..h], inclusive, l <= h


@dataclass(frozen=True)
class LinearConstraint:
    """sum(coeffs[v] * v) sense rhs; coeffs are nonzero ints."""
    coeffs: Tuple[Tuple[str, int], ...]
    sense: str  # "eq" | "le" | "ge"
    rhs: int

    def __post_init__(self):
        if self.sense not in ("eq", "le", "ge"):
            raise ValueError("sense must be eq, le or ge")
        if any(a == 0 for _, a in self.coeffs):
            raise ValueError("zero coefficients are not allowed")


def _tighten_ineq(pos: List[Tuple[str, int]], neg: List[Tuple[str, int]],
                  b: int, dom: Dict[str, Domain]) -> Optional[Dict[str, Domain]]:
    """One pass of LINEAR INEQUALITY 1 for
    sum_POS a_i x_i - sum_NEG a_i x_i <= b. Returns tightened domains
    or None on failure (empty interval)."""
    out = dict(dom)

    def bounds(v):
        return out[v]

    for j, aj in pos:
        # alpha_j = (b - sum_{POS-{j}} a_i l_i + sum_{NEG} a_i h_i) / a_j
        num = Fraction(b)
        for i, ai in pos:
            if i != j:
                num -= ai * bounds(i)[0]
        for i, ai in neg:
            num += ai * bounds(i)[1]
        h_new = min(bounds(j)[1], floor(num / aj))
        l_new = bounds(j)[0]
        if l_new > h_new:
            return None
        out[j] = (l_new, h_new)
    for j, aj in neg:
        # beta_j = (-b + sum_POS a_i l_i - sum_{NEG-{j}} a_i h_i) / a_j
        num = Fraction(-b)
        for i, ai in pos:
            num += ai * bounds(i)[0]
        for i, ai in neg:
            if i != j:
                num -= ai * bounds(i)[1]
        l_new = max(bounds(j)[1] * 0 + bounds(j)[0], ceil(num / aj))
        h_new = bounds(j)[1]
        if l_new > h_new:
            return None
        out[j] = (l_new, h_new)
    return out


def _split(c: LinearConstraint):
    pos = [(v, a) for v, a in c.coeffs if a > 0]
    neg = [(v, -a) for v, a in c.coeffs if a < 0]
    return pos, neg


def propagate(constraints: List[LinearConstraint],
              domains: Dict[str, Domain]) -> Optional[Dict[str, Domain]]:
    """Fixpoint of the domain reduction rules (Apt sec. 3.2.6-6.4).
    None = failure (some interval emptied)."""
    dom = dict(domains)
    for c in constraints:
        for v, _ in c.coeffs:
            if v not in dom:
                raise ValueError(f"constraint mentions unknown variable {v}")
    changed = True
    while changed:
        changed = False
        for c in constraints:
            pos, neg = _split(c)
            directions = []
            if c.sense in ("le", "eq"):
                directions.append((pos, neg, c.rhs))
            if c.sense in ("ge", "eq"):
                directions.append((neg, pos, -c.rhs))
            for p, n, b in directions:
                new = _tighten_ineq(p, n, b, dom)
                if new is None:
                    return None
                if new != dom:
                    changed = True
                    dom = new
    return dom


def is_solved(domains: Dict[str, Domain]) -> bool:
    return all(l == h for l, h in domains.values())


def solve_mac(constraints: List[LinearConstraint],
              domains: Dict[str, Domain]) -> Optional[Dict[str, int]]:
    """Backtracking search maintaining bounds consistency (Apt sec.
    8.6.3 MAC): propagate, split the smallest remaining domain,
    recurse. Returns one solution or None."""
    dom = propagate(constraints, domains)
    if dom is None:
        return None
    if is_solved(dom):
        return {v: l for v, (l, _h) in dom.items()}
    # smallest-domain variable first (Apt sec. 8.8.1 heuristic)
    var = min((v for v in dom if dom[v][0] < dom[v][1]),
              key=lambda v: dom[v][1] - dom[v][0])
    l, h = dom[var]
    mid = (l + h) // 2
    for lo, hi in ((l, mid), (mid + 1, h)):
        sub = dict(dom)
        sub[var] = (lo, hi)
        result = solve_mac(constraints, sub)
        if result is not None:
            return result
    return None


def enumerate_solutions(constraints: List[LinearConstraint],
                        domains: Dict[str, Domain],
                        limit: int = 100000) -> List[Dict[str, int]]:
    """All solutions (up to limit), via MAC with solution collection.
    Used by tests as the cross-check baseline."""
    found: List[Dict[str, int]] = []

    def rec(dom):
        if len(found) >= limit:
            return
        dom = propagate(constraints, dom)
        if dom is None:
            return
        if is_solved(dom):
            found.append({v: l for v, (l, _h) in dom.items()})
            return
        var = min((v for v in dom if dom[v][0] < dom[v][1]),
                  key=lambda v: dom[v][1] - dom[v][0])
        l, h = dom[var]
        mid = (l + h) // 2
        for lo, hi in ((l, mid), (mid + 1, h)):
            sub = dict(dom)
            sub[var] = (lo, hi)
            rec(sub)

    rec(dict(domains))
    return found
