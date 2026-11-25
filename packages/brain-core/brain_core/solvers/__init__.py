"""Solver adapters. Two independent formulations of the same problem
(cpsat_solver: interval/no_overlap; ordering_solver: Li linear ordering)
cross-validated against the exhaustive baseline in tests.
"""

from .cpsat_solver import solve_cpsat  # noqa: F401
from .ordering_solver import solve_ordering  # noqa: F401
from .result import Assignment, SolveResult, SolveStatus  # noqa: F401
