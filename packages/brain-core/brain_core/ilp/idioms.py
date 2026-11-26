"""ILP modeling idioms as CP-SAT constraint builders.

Source: Gusfield, Integer Linear Programming in Computational and
Systems Biology (Cambridge 2019; BCB tutorial Part IV). An idiom is a
logical construct plus the linear inequalities that implement it. The
key pattern: give each inequality L >= b an indicator variable z that
is forced to 1 when the inequality holds (If-Then), or forced to 0
when it fails (Only-If), then relate the indicators.

Idiom (17) If-Then:  L - M*z <= b - 1, with M an upper bound on L.
Idiom (18) Only-If:  L + m*z >= m + b, with m = s - b and s a lower
                     bound on L.
Idiom (27) NOT-EQUAL for bounded integer variables.
Composite NAND / OR / XOR / implied-satisfaction for inequalities.

Each builder takes explicit bounds (M or s) rather than computing
them, because the caller knows the variable domains; passing them
makes the strength of the encoding visible at the call site.
"""

from __future__ import annotations

from typing import Sequence

from ortools.sat.python import cp_model

LinearExpr = cp_model.LinearExpr


def add_if_then(model: cp_model.CpModel, L: LinearExpr, b: int,
                z: cp_model.IntVar, M: int) -> None:
    """If L >= b then z = 1 (idiom 17). M must upper-bound L."""
    model.add(L - M * z <= b - 1)


def add_only_if(model: cp_model.CpModel, L: LinearExpr, b: int,
                z: cp_model.IntVar, s: int) -> None:
    """z = 1 only if L >= b (idiom 18). s must lower-bound L."""
    m = s - b
    model.add(L + m * z >= m + b)


def add_iff(model: cp_model.CpModel, L: LinearExpr, b: int,
            z: cp_model.IntVar, s: int, M: int) -> None:
    """z = 1 if and only if L >= b (If-Then + Only-If)."""
    add_if_then(model, L, b, z, M)
    add_only_if(model, L, b, z, s)


def add_not_equal(model: cp_model.CpModel, x: cp_model.IntVar,
                  y: cp_model.IntVar, n: int,
                  z: cp_model.IntVar | None = None) -> cp_model.IntVar:
    """Force x != y for integer variables bounded in [1, n] (idiom
    27). Returns the fresh binary z used (x - y >= 1 if z = 0,
    y - x >= 1 if z = 1)."""
    if z is None:
        z = model.new_bool_var("neq_z")
    # weighted_sum keeps every operand one LinearExpr type: ortools
    # 9.12 cannot subtract an IntAffine from an IntWeightedSum
    model.add(cp_model.LinearExpr.weighted_sum([x, y, z], [1, -1, -n])
              >= 1 - n)
    model.add(cp_model.LinearExpr.weighted_sum([x, y, z], [-1, 1, n]) >= 1)
    return z


def add_not_equal_indicator(model: cp_model.CpModel, x: cp_model.IntVar,
                            y: cp_model.IntVar,
                            z: cp_model.IntVar) -> None:
    """z = 1 if binary x != binary y (idiom 25): z >= x - y and
    z >= y - x, plus z <= x + y and z <= 2 - x - y so z is 0 when
    they are equal (the book gives the If-Then direction (25); the
    Only-If direction completes the indicator)."""
    model.add(z >= x - y)
    model.add(z >= y - x)
    model.add(z <= x + y)
    model.add(z <= 2 - x - y)


def add_nand(model: cp_model.CpModel,
             ineqs: Sequence[tuple[LinearExpr, int, int, int]]) -> None:
    """At most one of the inequalities L_i >= b_i holds. Each entry is
    (L, b, s, M): the linear expression, its threshold, and lower/upper
    bounds on L. Uses add_iff per inequality, then sum z_i <= 1."""
    zs = []
    for L, b, s, M in ineqs:
        z = model.new_bool_var("nand_z")
        add_iff(model, L, b, z, s, M)
        zs.append(z)
    model.add(sum(zs) <= 1)


def add_or(model: cp_model.CpModel,
           ineqs: Sequence[tuple[LinearExpr, int, int, int]]) -> None:
    """At least one of the inequalities L_i >= b_i holds (idiom 20).
    Each entry is (L, b, s, M)."""
    zs = []
    for L, b, s, M in ineqs:
        z = model.new_bool_var("or_z")
        add_iff(model, L, b, z, s, M)
        zs.append(z)
    model.add(sum(zs) >= 1)


def add_xor(model: cp_model.CpModel,
            ineqs: Sequence[tuple[LinearExpr, int, int, int]]) -> None:
    """Exactly one of the inequalities L_i >= b_i holds (idiom 22).
    Each entry is (L, b, s, M)."""
    zs = []
    for L, b, s, M in ineqs:
        z = model.new_bool_var("xor_z")
        add_iff(model, L, b, z, s, M)
        zs.append(z)
    model.add(sum(zs) == 1)


def add_implied_satisfaction(model: cp_model.CpModel,
                             L1: LinearExpr, b1: int, s1: int, M1: int,
                             L2: LinearExpr, b2: int, s2: int, M2: int
                             ) -> None:
    """If L1 >= b1 then L2 >= b2 (idiom 23): indicator z1 for the
    first inequality (If-Then), z2 for the second (Only-If), z1 <= z2."""
    z1 = model.new_bool_var("imp_z1")
    z2 = model.new_bool_var("imp_z2")
    add_if_then(model, L1, b1, z1, M1)
    add_only_if(model, L2, b2, z2, s2)
    model.add(z1 <= z2)
