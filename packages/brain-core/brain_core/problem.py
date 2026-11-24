"""Solver-neutral problem representation (Stage 3, blueprint step 1).

Solver adapters receive ONLY this object. No solver types (ortools, pyomo)
leak into it, so a second adapter (HiGHS, later) consumes the same input.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .domain import FactoryInput


@dataclass(frozen=True)
class ProblemOrder:
    id: str
    processing_time: int
    due_date: int
    weight: float
    deadline: Optional[int]


@dataclass(frozen=True)
class SchedulingProblem:
    """One machine, N orders, minimize total weighted tardiness."""

    machine_id: str
    orders: List[ProblemOrder]

    @property
    def horizon(self) -> int:
        """Tight upper bound on any useful completion time.

        With a tardiness-only objective and no release dates there is never
        a reason to idle past the sum of processing times.
        """
        return sum(o.processing_time for o in self.orders)


def from_factory_input(data: FactoryInput) -> SchedulingProblem:
    """Convert validated domain records into the solver-neutral form."""
    return SchedulingProblem(
        machine_id=data.machine.id,
        orders=[
            ProblemOrder(
                id=o.id,
                processing_time=o.processing_time,
                due_date=o.due_date,
                weight=o.weight,
                deadline=o.deadline,
            )
            for o in data.orders
        ],
    )
