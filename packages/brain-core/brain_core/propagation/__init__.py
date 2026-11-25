"""Unary/cumulative resource propagation (Handbook of CP, sec. 22.3).

propagate() is the sec. 22.3.1 fixpoint (disjunctive + edge-finding +
not-first/not-last). propagate_all() adds the sec. 22.3.2 timetable
compulsory-part rules to the fixpoint; it is the full unary propagator.
"""

from typing import List

from .edge_finding import Activity, Infeasible, propagate
from .timetable import CumulativeActivity, compulsory_overload, timetable_unary
from .energy import required_energy, energy_overload_check


def propagate_all(activities: List[Activity]) -> List[Activity]:
    """Fixpoint of sec. 22.3.1 propagation and the 22.3.2 timetable rules."""
    acts = list(activities)
    while True:
        tightened = timetable_unary(propagate(acts))
        if [(a.r, a.d) for a in tightened] == [(a.r, a.d) for a in acts]:
            return tightened
        acts = tightened


__all__ = [
    "Activity",
    "CumulativeActivity",
    "Infeasible",
    "compulsory_overload",
    "energy_overload_check",
    "propagate",
    "propagate_all",
    "required_energy",
    "timetable_unary",
]
