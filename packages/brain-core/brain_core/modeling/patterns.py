"""Solver-neutral LP/MIP modeling patterns (Williams ch.3, 9, 10).

Each function returns LinearConstraint / Objective structures that any solver
adapter (CP-SAT now, HiGHS/Pyomo later) can translate. Keeping the patterns
here, once, tested, means no adapter re-derives Williams' algebra by hand.

Conventions (Williams 9.1): delta variables are 0-1; M is an upper bound and
m a lower bound on the constrained expression; eps is the tolerance beyond
which a constraint counts as violated (1 when all data is integer).

Two rules from the book are enforced here, not just documented:
- realistic-M: every function that needs a big-M takes it as a required
  argument, so the caller must compute a true bound (10.1: oversize M weakens
  the LP relaxation and can admit spurious integer solutions);
- disaggregation: the weak aggregated forms (10.11, 10.21) are deliberately
  not offered; disaggregate() produces the tight per-variable form (10.14).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# senses follow Williams' inequality forms
LE, GE, EQ = "<=", ">=", "=="


@dataclass(frozen=True)
class LinearConstraint:
    """sum(coeffs[var] * var) <sense> rhs. vars are named, solver-neutral."""

    coeffs: Dict[str, float]
    sense: str
    rhs: float
    label: str = ""

    def __post_init__(self):
        if self.sense not in (LE, GE, EQ):
            raise ValueError(f"bad sense {self.sense!r}")
        if not self.coeffs:
            raise ValueError("constraint with no terms")

    def lhs(self, values: Dict[str, float]) -> float:
        return sum(c * values[v] for v, c in self.coeffs.items())

    def holds(self, values: Dict[str, float], tol: float = 1e-9) -> bool:
        lhs = self.lhs(values)
        if self.sense == LE:
            return lhs <= self.rhs + tol
        if self.sense == GE:
            return lhs >= self.rhs - tol
        return abs(lhs - self.rhs) <= tol


@dataclass
class Objective:
    """Linear objective terms to add: sum(coeffs[var] * var), minimize."""

    coeffs: Dict[str, float] = field(default_factory=dict)

    def add(self, var: str, coeff: float) -> None:
        self.coeffs[var] = self.coeffs.get(var, 0.0) + coeff


def indicator_link(x: str, delta: str, upper_x: float) -> LinearConstraint:
    """x > 0 -> delta = 1, as x - M*delta <= 0 (Williams 9.1, eq. 9.1).

    upper_x is the realistic upper bound M on x; it is required (not
    defaulted) so the caller must think about it (10.1).
    The reverse implication (delta = 1 -> x >= threshold) is intentionally
    absent: it needs a practical threshold m, and where cost minimization
    pushes delta down, optimality enforces it for free (Example 9.1).
    """
    if upper_x <= 0:
        raise ValueError("upper_x must be a positive realistic bound")
    return LinearConstraint({x: 1.0, delta: -upper_x}, LE, 0.0,
                            label=f"indicator_link({x},{delta})")


def fixed_charge(x: str, delta: str, upper_x: float,
                 unit_cost: float, setup_cost: float
                 ) -> Tuple[List[LinearConstraint], Objective]:
    """Cost = unit_cost*x + setup_cost*delta, with the indicator link.

    Williams Example 9.1: producing any quantity incurs the setup cost.
    """
    obj = Objective()
    obj.add(x, unit_cost)
    obj.add(delta, setup_cost)
    return [indicator_link(x, delta, upper_x)], obj


def soft_constraint(coeffs: Dict[str, float], sense: str, rhs: float,
                    penalty_over: float, penalty_under: float = 0.0,
                    label: str = "soft"
                    ) -> Tuple[List[LinearConstraint], Objective, List[str]]:
    """Make a hard constraint violable at a price (Williams 3.3.6, 3.3.8).

    Returns (constraints, objective_terms, deviation_vars). For "<=" we add
    u >= 0 with a.x - u <= b and penalty_over on u. For ">=" the deviation is
    v with a.x + v >= b and penalty_over on v. For "==" both (Williams 3.11):
    a.x + u - v = b, where v measures over-achievement (penalty_over) and u
    under-achievement (penalty_under). Our due_date/deadline split is this
    pattern with deadline = the hard form.
    """
    obj = Objective()
    over, under = f"{label}_over", f"{label}_under"
    if sense == LE:
        obj.add(over, penalty_over)
        return [LinearConstraint({**coeffs, over: -1.0}, LE, rhs, label)], obj, [over]
    if sense == GE:
        obj.add(under, penalty_over)
        return [LinearConstraint({**coeffs, under: 1.0}, GE, rhs, label)], obj, [under]
    obj.add(under, penalty_under)
    obj.add(over, penalty_over)
    u, v = under, over
    return [LinearConstraint({**coeffs, u: 1.0, v: -1.0}, EQ, rhs, label)], obj, [u, v]


def at_least_k(deltas: List[str], k: int, label: str = "at_least") -> LinearConstraint:
    """At least k of the 0-1 variables are 1 (Williams 9.4.1, eq. 9.81)."""
    if not 1 <= k <= len(deltas):
        raise ValueError(f"k={k} outside 1..{len(deltas)}")
    return LinearConstraint({d: 1.0 for d in deltas}, GE, float(k), label)


def at_most_k(deltas: List[str], k: int, label: str = "at_most") -> LinearConstraint:
    """At most k of the 0-1 variables are 1 (Williams 9.4.1)."""
    if not 0 <= k < len(deltas):
        raise ValueError(f"k={k} outside 0..{len(deltas) - 1}")
    return LinearConstraint({d: 1.0 for d in deltas}, LE, float(k), label)


def disjunction(alternatives: List[Tuple[Dict[str, float], str, float, float]],
                deltas: List[str], label: str = "or") -> List[LinearConstraint]:
    """At least one of N constraints must hold (Williams 9.4.1, eq. 9.77-9.79).

    Each alternative is (coeffs, sense, rhs, M) where M is a realistic bound:
    for "<=", M >= max(a.x - b); for ">=", M >= max(b - a.x). Indicator i
    forces its constraint via delta_i = 1; the disjunctive sum forces at
    least one indicator on. "And" needs no pattern: plain LP constraints.
    """
    if len(alternatives) != len(deltas):
        raise ValueError("one delta per alternative")
    if len(alternatives) < 2:
        raise ValueError("a disjunction needs at least two alternatives")
    out: List[LinearConstraint] = []
    for (coeffs, sense, rhs, m), d in zip(alternatives, deltas):
        if m <= 0:
            raise ValueError("each alternative needs a positive realistic M")
        if sense == LE:
            # a.x + M*delta <= M + b  (Williams 9.12)
            out.append(LinearConstraint({**coeffs, d: m}, LE, m + rhs,
                                        f"{label}_arm"))
        elif sense == GE:
            # a.x - M*delta >= b - M  (mirror of 9.12)
            out.append(LinearConstraint({**coeffs, d: -m}, GE, rhs - m,
                                        f"{label}_arm"))
        else:
            raise ValueError("use soft/indicator forms for EQ arms")
    out.append(at_least_k(deltas, 1, label=f"{label}_pick"))
    return out


def minimax(exprs: List[Dict[str, float]], z: str = "z_max"
            ) -> List[LinearConstraint]:
    """minimize max_i(expr_i): introduce z, add expr_i - z <= 0 (Williams 3.2.3)."""
    if not exprs:
        raise ValueError("minimax needs at least one expression")
    return [LinearConstraint({**e, z: -1.0}, LE, 0.0, "minimax") for e in exprs]


def disaggregate(deltas: List[str], delta: str) -> List[LinearConstraint]:
    """Replace sum(d_i) - n*d <= 0 by the tighter d_i - d <= 0 chain.

    Williams 10.1.2 (10.11 -> 10.14): identical integer solutions, strictly
    tighter LP relaxation. Always prefer this form.
    """
    return [LinearConstraint({d_i: 1.0, delta: -1.0}, LE, 0.0,
                             f"disaggregate({d_i})") for d_i in deltas]


def symmetry_break_order(vars_: List[str]) -> List[LinearConstraint]:
    """v1 >= v2 >= ... ordering to kill symmetric solutions (Williams 10.2.7).

    Use when identical resources (machines, vehicles, workers) make solutions
    interchangeable; each constraint is v_i - v_{i+1} >= 0.
    """
    if len(vars_) < 2:
        raise ValueError("ordering needs at least two variables")
    return [LinearConstraint({a: 1.0, b: -1.0}, GE, 0.0,
                             f"symmetry({a}>={b})")
            for a, b in zip(vars_, vars_[1:])]
