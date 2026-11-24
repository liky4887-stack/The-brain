"""Solver-neutral modeling patterns distilled from Williams, Model Building in
Mathematic Programming (5th ed.). See docs/BOOKS.md and the williams-model-building
skill. Every pattern here is brute-force-verified in tests/test_modeling_patterns.py.
"""

from brain_core.modeling.patterns import (  # noqa: F401
    LinearConstraint,
    Objective,
    at_least_k,
    at_most_k,
    disaggregate,
    disjunction,
    fixed_charge,
    indicator_link,
    minimax,
    soft_constraint,
    symmetry_break_order,
)
