"""Pinedo ch.4-5: CPM and the disjunctive-graph job shop model.

CPM is locked on Example 4.2.3 (precedence set reconstructed from, and
verified against, the book's printed earliest AND latest completion
rows) and cross-checked against brute-force longest paths on random DAGs.
The disjunctive graph is validated against direct schedule simulation,
and its optimum against enumeration of all machine sequences.
"""

import itertools
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.jobshop import CycleError, JobShopInstance, cpm, makespan

# --- Example 4.2.3 (Pinedo): 14 jobs. Processing times printed in the
# book; precedences reconstructed from Figure 4.4 AND verified: they
# reproduce both the book's earliest and its latest completion rows.

P423 = {str(j): p for j, p in enumerate(
    [5, 6, 9, 12, 7, 12, 10, 6, 10, 9, 7, 8, 7, 5], start=1)}
PREDS423 = {
    "1": set(), "2": {"1"}, "3": {"1"}, "4": {"2"}, "5": {"3"},
    "6": {"3"}, "7": {"4"}, "8": {"5", "6"}, "9": {"6"}, "10": {"7"},
    "11": {"8", "9"}, "12": {"10", "11"}, "13": {"11"}, "14": {"12", "13"},
}
EARLIEST423 = dict(zip(P423, [5, 11, 14, 23, 21, 26, 33, 32, 36, 42, 43, 51, 50, 56]))
LATEST423 = dict(zip(P423, [5, 12, 14, 24, 30, 26, 34, 36, 36, 43, 43, 51, 51, 56]))


def test_cpm_book_example_4_2_3():
    res = cpm(P423, {k: set(v) for k, v in PREDS423.items()})
    assert res.makespan == 56
    assert res.earliest_finish == EARLIEST423
    assert res.latest_finish == LATEST423
    assert res.critical == ["1", "3", "6", "9", "11", "12", "14"]


def brute_longest_path(processing, predecessors):
    best = 0
    for j in processing:
        chain_max = processing[j] + max(
            (brute_helper(k, processing, predecessors) for k in predecessors[j]),
            default=0)
        best = max(best, chain_max)
    return best


def brute_helper(j, processing, predecessors):
    return processing[j] + max(
        (brute_helper(k, processing, predecessors) for k in predecessors[j]),
        default=0)


def test_cpm_matches_brute_force_random_dags():
    rng = random.Random(42)
    for _ in range(150):
        n = rng.randint(1, 9)
        processing = {str(j): rng.randint(1, 9) for j in range(n)}
        predecessors = {
            str(j): {str(k) for k in range(j) if rng.random() < 0.3}
            for j in range(n)
        }
        res = cpm(processing, predecessors)
        assert res.makespan == brute_longest_path(processing, predecessors)
        for j in processing:
            assert res.slack[j] == res.latest_start[j] - res.earliest_start[j] >= 0
            assert res.earliest_finish[j] == res.earliest_start[j] + processing[j]
            assert res.latest_finish[j] == res.latest_start[j] + processing[j]


def test_cpm_cycle_detected():
    with pytest.raises(ValueError):
        cpm({"a": 1, "b": 2}, {"a": {"b"}, "b": {"a"}})


# --- Example 5.3.1 (Pinedo): 4 machines, 3 jobs.

EX531 = JobShopInstance(routes=(
    (("1", 10), ("2", 8), ("3", 4)),
    (("2", 8), ("1", 3), ("4", 5), ("3", 6)),
    (("1", 4), ("2", 7), ("4", 3)),
))


def simulate(instance, sequences):
    """Direct simulation: each machine runs its sequence as early as
    possible respecting job routes. Returns (makespan, starts)."""
    starts = {}
    machine_free = {m: 0 for m in sequences}
    job_free = [0] * len(instance.routes)
    remaining = {m: list(seq) for m, seq in sequences.items()}
    progress = True
    while any(remaining[m] for m in remaining):
        if not progress:
            raise CycleError("simulation deadlock")
        progress = False
        for m in list(remaining):
            if not remaining[m]:
                continue
            j, pos = remaining[m][0]
            route = instance.routes[j]
            if pos > 0 and (j, pos - 1) not in starts:
                continue  # predecessor operation not done
            p = route[pos][1]
            s = max(machine_free[m], job_free[j])
            starts[(j, pos)] = s
            machine_free[m] = s + p
            job_free[j] = s + p
            remaining[m].pop(0)
            progress = True
    return max(job_free), starts


def all_sequences(instance):
    """All machine-sequence dicts for small instances."""
    machines = {}
    for j, route in enumerate(instance.routes):
        for pos, (m, p) in enumerate(route):
            machines.setdefault(m, []).append((j, pos))
    per_machine = [list(itertools.permutations(ops)) for ops in machines.values()]
    keys = list(machines)
    for combo in itertools.product(*per_machine):
        yield {m: list(seq) for m, seq in zip(keys, combo)}


def test_disjunctive_graph_matches_simulation_and_enumeration():
    best_graph = None
    best_sim = None
    n_checked = 0
    for seq in all_sequences(EX531):
        try:
            g, chain = makespan(EX531, seq)
        except CycleError:
            with pytest.raises(CycleError):
                simulate(EX531, seq)
            continue
        s, _ = simulate(EX531, seq)
        assert g == s, (seq, g, s)
        # chain endpoints must be consistent with the makespan
        assert chain[-1][3] == g
        best_graph = g if best_graph is None else min(best_graph, g)
        best_sim = s if best_sim is None else min(best_sim, s)
        n_checked += 1
    assert n_checked > 60  # cyclic selections are skipped by design
    assert best_graph == best_sim


def test_disjunctive_cycle_detection():
    # Force a cycle: machine "1" sequence (job0,pos0)->(job1,pos1) and
    # machine "2" sequence (job1,pos0)->(job0,pos1) on a 2x2 shop.
    inst = JobShopInstance(routes=(
        (("1", 3), ("2", 3)),
        (("2", 3), ("1", 3)),
    ))
    with pytest.raises(CycleError):
        makespan(inst, {"1": [(1, 1), (0, 0)], "2": [(0, 1), (1, 0)]})
    # The feasible orientation: both machines run in parallel, makespan 6.
    g, _ = makespan(inst, {"1": [(0, 0), (1, 1)], "2": [(1, 0), (0, 1)]})
    assert g == 6
