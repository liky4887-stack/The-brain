"""Time-bound propagation for a unary (disjunctive) resource.

Source: Handbook of Constraint Programming (Rossi, van Beek, Walsh, eds.,
Elsevier 2006), ch.22 by Baptiste, Laborie, Le Pape, Nuijten - sec. 22.3.1
(disjunctive constraint, edge-finding). Digital text, no OCR.

Model: non-preemptive activities on one machine. Activity i has an
earliest start time r_i, a latest end time d_i, and a minimal processing
time p_i. Propagation is a purely deductive process: it tightens the
bounds and detects contradictions without searching.

Two mechanisms from the chapter are implemented:

1. Disjunctive constraint propagation (arc-B-consistency on
   [end(Ai) <= start(Aj)] or [end(Aj) <= start(Ai)]): when the earliest
   end time of Ai exceeds the latest start time of Aj, Ai cannot precede
   Aj, so Aj must precede Ai and bounds tighten. Both impossible means
   contradiction.

2. Edge-finding, in the straightforward cubic form described in the
   chapter: the rules quantify over sets Omega, but it suffices to
   consider "task interval" sets Omega(t1, t2) = {Aj : t1 <= r_j and
   d_j <= t2} for O(n^2) intervals, giving O(n^3) overall.

       d_{Omega u {Ai}} - r_Omega < p_Omega + p_i   =>   Ai before Omega
       d_Omega - r_{Omega u {Ai}} < p_Omega + p_i   =>   Ai after Omega

   and the adjustments end(Ai) <= min over nonempty Omega' of
   (d_Omega' - p_Omega'), start(Ai) >= max over nonempty Omega' of
   (r_Omega' + p_Omega'), with Omega' restricted to task-interval subsets
   of Omega (sound for any subset; strength beyond that is not claimed).

Honesty: propagation is sound but incomplete. Tests check soundness
against brute-force permutation search: every tightened bound holds in
every feasible schedule, and a detected contradiction implies true
infeasibility. Completeness is NOT claimed or tested.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Tuple


class Infeasible(Exception):
    """Propagation detected a contradiction: no feasible schedule exists."""


@dataclass(frozen=True)
class Activity:
    name: str
    r: int  # earliest start time
    d: int  # latest end time
    p: int  # (minimal) processing time

    def __post_init__(self):
        if self.p < 0:
            raise ValueError("processing time must be nonnegative")
        if self.r + self.p > self.d:
            raise Infeasible(f"{self.name}: window [{self.r},{self.d}] too small for p={self.p}")


def _task_intervals(acts: List[Activity]) -> List[Tuple[int, int]]:
    points = sorted({a.r for a in acts} | {a.d for a in acts})
    return [(t1, t2) for t1 in points for t2 in points if t1 < t2]


def _omega(acts: List[Activity], t1: int, t2: int) -> List[int]:
    return [j for j, a in enumerate(acts) if a.r >= t1 and a.d <= t2]


def propagate(activities: List[Activity]) -> List[Activity]:
    """Tighten bounds by fixpoint disjunctive + edge-finding propagation.

    Returns new Activity objects with tightened (r, d). Raises Infeasible
    when a contradiction is detected.
    """
    acts = list(activities)
    changed = True
    while changed:
        changed = False
        acts = _disjunctive_pass(acts)
        acts, ef_changed = _edge_finding_pass(acts)
        acts, nfl_changed = _not_first_last_pass(acts)
        changed = ef_changed or nfl_changed
    return acts


def _disjunctive_pass(acts: List[Activity]) -> List[Activity]:
    n = len(acts)
    out = list(acts)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = out[i], out[j]
            eet_a, lst_a = a.r + a.p, a.d - a.p
            eet_b, lst_b = b.r + b.p, b.d - b.p
            a_can_precede = eet_a <= lst_b
            b_can_precede = eet_b <= lst_a
            if not a_can_precede and not b_can_precede:
                raise Infeasible(f"{a.name} and {b.name} cannot be sequenced")
            if not a_can_precede:
                # b before a: start(a) >= eet(b), end(b) <= lst(a)
                na = replace(a, r=max(a.r, eet_b))
                nb = replace(b, d=min(b.d, lst_a))
                out[i], out[j] = na, nb
            elif not b_can_precede:
                nb = replace(b, r=max(b.r, eet_a))
                na = replace(a, d=min(a.d, lst_b))
                out[i], out[j] = na, nb
    return out


def _edge_finding_pass(acts: List[Activity]) -> Tuple[List[Activity], bool]:
    n = len(acts)
    out = list(acts)
    changed = False
    intervals = _task_intervals(acts)
    # Precompute task-interval subsets' aggregates for the adjustment step.
    for t1, t2 in intervals:
        omega = _omega(acts, t1, t2)
        if not omega:
            continue
        r_om = min(acts[j].r for j in omega)
        d_om = max(acts[j].d for j in omega)
        p_om = sum(acts[j].p for j in omega)
        # Adjustment candidates: task-interval subsets of omega.
        subs = []
        for u1, u2 in intervals:
            sub = [j for j in omega if acts[j].r >= u1 and acts[j].d <= u2]
            if sub:
                r_s = min(acts[j].r for j in sub)
                d_s = max(acts[j].d for j in sub)
                p_s = sum(acts[j].p for j in sub)
                subs.append((r_s, d_s, p_s))
        for i in range(n):
            if i in omega:
                continue
            a = acts[i]
            # Ai before Omega? (d of a set = LARGEST latest end time)
            if max(d_om, a.d) - r_om < p_om + a.p:
                if subs:
                    new_d = min(d_s - p_s for _, d_s, p_s in subs)
                    if new_d < out[i].d:
                        out[i] = replace(out[i], d=new_d)
                        changed = True
                        if out[i].r + out[i].p > out[i].d:
                            raise Infeasible(f"{a.name}: edge-finding emptied its window")
            # Ai after Omega? (r of a set = SMALLEST earliest start time)
            if d_om - min(r_om, a.r) < p_om + a.p:
                if subs:
                    new_r = max(r_s + p_s for r_s, _, p_s in subs)
                    if new_r > out[i].r:
                        out[i] = replace(out[i], r=new_r)
                        changed = True
                        if out[i].r + out[i].p > out[i].d:
                            raise Infeasible(f"{a.name}: edge-finding emptied its window")
    return out, changed


def _not_first_last_pass(acts: List[Activity]) -> Tuple[List[Activity], bool]:
    """Not-first / not-last rules (sec. 22.3.1).

    Ai cannot be first in Omega u {Ai} when d_Ai - r_Omega < p_Omega + p_i:
    then end(Ai) <= max over B in Omega of lst(B). Mirror for not-last:
    d_Omega - r_Ai < p_Omega + p_i => start(Ai) >= min over B in Omega of
    eet(B). Sets Omega restricted to task intervals, as for edge-finding.
    """
    n = len(acts)
    out = list(acts)
    changed = False
    for t1, t2 in _task_intervals(acts):
        omega = _omega(acts, t1, t2)
        if not omega:
            continue
        r_om = min(acts[j].r for j in omega)
        d_om = max(acts[j].d for j in omega)
        p_om = sum(acts[j].p for j in omega)
        max_lst = max(acts[j].d - acts[j].p for j in omega)
        min_eet = min(acts[j].r + acts[j].p for j in omega)
        for i in range(n):
            if i in omega:
                continue
            a = acts[i]
            if a.d - r_om < p_om + a.p:  # Ai not first
                if max_lst < out[i].d:
                    out[i] = replace(out[i], d=max_lst)
                    changed = True
                    if out[i].r + out[i].p > out[i].d:
                        raise Infeasible(f"{a.name}: not-first emptied its window")
            if d_om - a.r < p_om + a.p:  # Ai not last
                if min_eet > out[i].r:
                    out[i] = replace(out[i], r=min_eet)
                    changed = True
                    if out[i].r + out[i].p > out[i].d:
                        raise Infeasible(f"{a.name}: not-last emptied its window")
    return out, changed
