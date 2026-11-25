"""CP-SAT solver for the disjunctive job shop (Stage 1 gate engine).

Model: one interval per operation, no_overlap per machine, precedence
along each job's route, minimize makespan (the standard CP model for
JSP; CP-SAT Primer: no_overlap is CP-SAT's strongest constraint).

Honesty rules: the solver returns start times only; the reported
makespan is RECOMPUTED by the independent validator in
jobshop/disjunctive.py (longest path in the disjunctive graph, Pinedo
ch.5.3) from the machine sequences implied by those starts. Status is
reported exactly as CP-SAT gave it: OPTIMAL only when CP-SAT proved
the bound, FEASIBLE otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from .disjunctive import CycleError, JobShopInstance, makespan


@dataclass(frozen=True)
class JobShopResult:
    status: str            # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "UNKNOWN"
    makespan: Optional[int]          # recomputed by the validator, None if no plan
    starts: Optional[Tuple[int, ...]]          # per operation, solver's answer
    validated: bool


def solve_jobshop(instance: JobShopInstance,
                  time_limit_s: float = 60.0,
                  workers: int = 8,
                  seed: int = 42) -> JobShopResult:
    ops = instance.operations()  # (machine, job, p), route order per job
    horizon = sum(p for _, _, p in ops)
    model = cp_model.CpModel()
    starts, ends, intervals = [], [], []
    by_machine: Dict[str, List[int]] = {}
    for idx, (machine, _job, p) in enumerate(ops):
        s = model.new_int_var(0, horizon, f"s{idx}")
        e = model.new_int_var(0, horizon, f"e{idx}")
        iv = model.new_interval_var(s, p, e, f"iv{idx}")
        starts.append(s)
        ends.append(e)
        intervals.append(iv)
        by_machine.setdefault(machine, []).append(idx)
    for machine, ids in by_machine.items():
        model.add_no_overlap([intervals[i] for i in ids])
    # conjunctive arcs: job routes
    pos = 0
    for route in instance.routes:
        for k in range(len(route) - 1):
            model.add(ends[pos + k] <= starts[pos + k + 1])
        pos += len(route)
    span = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(span, ends)
    model.minimize(span)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    status = solver.solve(model)
    status_name = solver.status_name(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return JobShopResult(status_name, None, None, False)
    start_values = tuple(int(solver.value(s)) for s in starts)
    recomputed = validate_schedule(instance, ops, start_values)
    return JobShopResult(status_name, recomputed, start_values, True)


def validate_schedule(instance: JobShopInstance,
                      ops: List[Tuple[str, int, int]],
                      starts: Tuple[int, ...]) -> int:
    """Independent check: order each machine by start times, recompute
    the makespan as the longest path in the disjunctive graph. Raises
    CycleError (infeasible selection) or ValueError (overlap/precedence
    violation) rather than trusting the solver."""
    by_machine: Dict[str, List[Tuple[int, int, int]]] = {}
    for idx, (machine, job, _p) in enumerate(ops):
        pos_in_route = _position(instance, job, idx)
        by_machine.setdefault(machine, []).append((starts[idx], job, pos_in_route))
    sequences: Dict[str, List[Tuple[int, int]]] = {}
    for machine, triples in by_machine.items():
        triples.sort(key=lambda t: t[0])
        sequences[machine] = [(j, p) for _, j, p in triples]
    ms, _critical = makespan(instance, sequences)  # raises CycleError if infeasible
    # explicit overlap check (the graph would catch it as a cycle only
    # in the reversed direction; make it direct):
    for machine, triples in by_machine.items():
        triples.sort(key=lambda t: t[0])
        for (s1, j1, p1), (s2, j2, p2) in zip(triples, triples[1:]):
            dur1 = _duration(instance, j1, p1)
            if s1 + dur1 > s2:
                raise ValueError(f"overlap on machine {machine}")
    # precedence check against the returned starts
    for j, route in enumerate(instance.routes):
        for pos in range(len(route) - 1):
            idx1 = _op_index(instance, j, pos)
            idx2 = _op_index(instance, j, pos + 1)
            if starts[idx1] + _duration(instance, j, pos) > starts[idx2]:
                raise ValueError(f"precedence violated in job {j}")
    return ms


def _position(instance: JobShopInstance, job: int, op_idx: int) -> int:
    base = sum(len(r) for r in instance.routes[:job])
    return op_idx - base


def _op_index(instance: JobShopInstance, job: int, pos: int) -> int:
    return sum(len(r) for r in instance.routes[:job]) + pos


def _duration(instance: JobShopInstance, job: int, pos: int) -> int:
    return instance.routes[job][pos][1]
