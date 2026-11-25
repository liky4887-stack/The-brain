"""Constraint propagation and search on integer intervals (Apt 2003)."""

from .bounds import (
    LinearConstraint,
    enumerate_solutions,
    is_solved,
    propagate,
    solve_mac,
)

__all__ = [
    "LinearConstraint", "enumerate_solutions", "is_solved", "propagate",
    "solve_mac",
]
