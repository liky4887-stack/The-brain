"""Energy reasoning: the left-shift/right-shift overload check.

Source: Handbook of Constraint Programming, sec. 22.3.2 (cumulative
resources, energy reasoning; the WSh definition is from [25] as given in
the chapter, with the Figure 22.6 example).

The required energy of activity Ai over [t1, t2) is
    WSh(Ai, t1, t2) = c_i * min(t2 - t1, p_i^+(t1), p_i^-(t2))
where p_i^+(t1) = max(0, p_i - max(0, t1 - r_i)) is what Ai executes
after t1 when left-shifted (started at r_i) and p_i^-(t2) = max(0, p_i -
max(0, d_i - t2)) is what it executes before t2 when right-shifted
(ended at d_i).

Overload check: if sum_i WSh(Ai, t1, t2) > C * (t2 - t1) for any
interval, no feasible schedule exists. Bound ADJUSTMENTS from energy
reasoning (the O(n^3) rules in the chapter) are NOT implemented.
"""

from __future__ import annotations

from typing import List

from .timetable import CumulativeActivity
from .edge_finding import Infeasible


def required_energy(a: CumulativeActivity, t1: int, t2: int) -> int:
    """WSh(Ai, t1, t2) as defined above."""
    p_plus = max(0, a.p - max(0, t1 - a.r))
    p_minus = max(0, a.p - max(0, a.d - t2))
    return a.c * min(t2 - t1, p_plus, p_minus)


def energy_overload_check(activities: List[CumulativeActivity], capacity: int) -> None:
    """Raise Infeasible when an interval demands more energy than it provides."""
    if capacity < 0:
        raise ValueError("capacity must be nonnegative")
    points = sorted({a.r for a in activities} | {a.d for a in activities})
    for t1 in points:
        for t2 in points:
            if t2 <= t1:
                continue
            need = sum(required_energy(a, t1, t2) for a in activities)
            if need > capacity * (t2 - t1):
                raise Infeasible(
                    f"energy {need} over [{t1},{t2}) exceeds {capacity * (t2 - t1)}")
