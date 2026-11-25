"""Timetable constraint propagation (Handbook of CP, sec. 22.3.2).

Unary resource: every activity with lst_i < eet_i has a compulsory part
[lst_i, eet_i) it must occupy. No other activity may overlap it, which
pushes bounds: an activity that cannot fit entirely before the compulsory
part must start after it, and the mirror; neither possible is a
contradiction.

Cumulative resource (capacity C): the compulsory profile sums the
demands c_i over each activity's compulsory part; if the profile exceeds
C at any time, the instance is infeasible. Bound adjustment from the
profile is NOT implemented (documented in the skill).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Tuple

from .edge_finding import Activity, Infeasible


def compulsory_part(a: Activity) -> Tuple[int, int]:
    """[lst, eet): times the activity must occupy. Empty when lst >= eet."""
    return (a.d - a.p, a.r + a.p)


def timetable_unary(activities: List[Activity]) -> List[Activity]:
    """One pass of timetable propagation on a unary resource."""
    out = list(activities)
    for a in activities:
        lo, hi = compulsory_part(a)
        if lo >= hi:
            continue  # no compulsory part
        for i, b in enumerate(out):
            if b is a or b.name == a.name:
                continue
            if b.r >= hi or b.d <= lo:
                continue  # no overlap possible
            can_before = b.r + b.p <= lo   # b can end before the part
            can_after = b.d - b.p >= hi    # b can start after the part
            if not can_before and not can_after:
                raise Infeasible(
                    f"{b.name} cannot avoid compulsory part of {a.name}")
            if not can_before:
                out[i] = replace(b, r=max(b.r, hi))
            elif not can_after:
                out[i] = replace(b, d=min(b.d, lo))
    return out


@dataclass(frozen=True)
class CumulativeActivity:
    name: str
    r: int
    d: int
    p: int
    c: int  # resource demand while executing

    def __post_init__(self):
        if self.p < 0 or self.c < 0:
            raise ValueError("processing time and demand must be nonnegative")
        if self.r + self.p > self.d:
            raise Infeasible(f"{self.name}: window too small")


def compulsory_overload(activities: List[CumulativeActivity], capacity: int) -> None:
    """Raise Infeasible if compulsory demands exceed capacity at any time."""
    if capacity < 0:
        raise ValueError("capacity must be nonnegative")
    points = sorted({a.r for a in activities} | {a.d for a in activities})
    for a in activities:
        if a.c > capacity:
            raise Infeasible(f"{a.name} alone exceeds capacity")
    for t1, t2 in zip(points, points[1:]):
        load = sum(a.c for a in activities
                   if a.d - a.p <= t1 and a.r + a.p >= t2)
        if load > capacity:
            raise Infeasible(
                f"compulsory load {load} over [{t1},{t2}) exceeds capacity {capacity}")
