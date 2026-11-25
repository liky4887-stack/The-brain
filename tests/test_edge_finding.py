"""Soundness of unary-resource propagation (Handbook of CP, ch.22.3.1).

Brute-force permutation search computes the true feasible schedules;
every bound the propagator deduces must hold in every feasible schedule,
and a detected contradiction must mean true infeasibility. Propagation is
incomplete by nature, so the reverse directions are NOT asserted.
"""

import itertools
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.propagation import Activity, Infeasible, propagate


def feasible_schedules(acts):
    """All permutation schedules respecting windows; list of start dicts."""
    out = []
    n = len(acts)
    for perm in itertools.permutations(range(n)):
        t = 0
        starts = {}
        ok = True
        for idx in perm:
            a = acts[idx]
            t = max(t, a.r)
            if t + a.p > a.d:
                ok = False
                break
            starts[idx] = t
            t += a.p
        if ok:
            out.append(starts)
    return out


def random_instance(rng, n):
    acts = []
    for i in range(n):
        p = rng.randint(1, 6)
        r = rng.randint(0, 8)
        d = r + p + rng.randint(0, 10)
        acts.append(Activity(f"A{i}", r, d, p))
    return acts


def test_propagation_is_sound_against_brute_force():
    rng = random.Random(22)
    n_contradictions = 0
    for trial in range(200):
        acts = random_instance(rng, rng.randint(2, 6))
        feasible = feasible_schedules(acts)
        try:
            tightened = propagate(acts)
        except Infeasible:
            # Soundness: contradiction only when truly infeasible.
            assert feasible == [], f"trial {trial}: false contradiction"
            n_contradictions += 1
            continue
        if not feasible:
            continue  # incomplete propagation missed it; allowed
        for i, a in enumerate(tightened):
            min_start = min(s[i] for s in feasible)
            max_end = max(s[i] + acts[i].p for s in feasible)
            # Deduced earliest start <= every feasible start...
            assert a.r <= min_start, (trial, i, a, min_start)
            # ...and every feasible end <= deduced latest end.
            assert max_end <= a.d, (trial, i, a, max_end)
    assert n_contradictions > 0  # the test actually exercises infeasibility


def test_bounds_only_tighten_and_fixpoint_is_stable():
    rng = random.Random(7)
    for _ in range(60):
        acts = random_instance(rng, rng.randint(2, 6))
        try:
            once = propagate(acts)
        except Infeasible:
            continue
        for orig, new in zip(acts, once):
            assert new.r >= orig.r and new.d <= orig.d
        twice = propagate(once)  # idempotent fixpoint
        assert [(a.r, a.d) for a in once] == [(a.r, a.d) for a in twice]


def test_disjunctive_detects_simple_contradiction():
    # Two activities, each p=4, windows force overlap: A in [0,5), B in [0,5).
    with pytest.raises(Infeasible):
        propagate([Activity("A", 0, 5, 4), Activity("B", 0, 5, 4)])


def test_disjunctive_orders_activities():
    # A must end by 6, B cannot start before 5, both p=2: A must go first.
    acts = propagate([Activity("A", 0, 6, 2), Activity("B", 5, 12, 2)])
    assert acts[0].d <= 7  # end(A) <= lst(B) = 10 -> tightened via B's window
    assert acts[1].r >= 2  # start(B) >= eet(A) = 2


def test_edge_finding_classic_example():
    # Three tasks crowded in [0,12) with p=5 each: they saturate the
    # window; a fourth task with a wide window must go before or after.
    acts = [
        Activity("X", 0, 100, 3),
        Activity("A", 0, 12, 5),
        Activity("B", 0, 12, 5),
        Activity("C", 0, 12, 5),
    ]
    tightened = propagate(acts)
    # X cannot fit inside [0,12): 4 tasks need 18 > 12. So X is before or
    # after {A,B,C}: start(X) >= 15 or end(X) <= 0 (latter impossible), so
    # the propagator must push start(X) to at least 15 OR push its end out
    # of the window. Either way its window must shrink to exclude [3,12).
    x = tightened[0]
    assert x.r >= 15 or x.d <= 12 - 15 + 3, f"no edge-finding deduction: {x}"
