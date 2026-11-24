"""Standard result object every solver adapter returns (blueprint step 4).

Statuses are honest: a time-limited or infeasible run is reported as such
and never dressed up as a plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class SolveStatus(str, Enum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"  # a plan exists but optimality is unproven (e.g. time limit)
    INFEASIBLE = "infeasible"
    TIME_LIMIT = "time_limit"  # no plan found within the limit
    ERROR = "error"


@dataclass(frozen=True)
class Assignment:
    order_id: str
    start: int
    end: int


@dataclass
class SolveResult:
    status: SolveStatus
    objective: Optional[float] = None  # total weighted tardiness, None without a plan
    assignments: List[Assignment] = field(default_factory=list)
    solve_time_ms: int = 0
    warnings: List[str] = field(default_factory=list)
    solver_diagnostics: Dict[str, object] = field(default_factory=dict)
