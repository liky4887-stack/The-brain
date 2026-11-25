"""Disjunctive graph model of a job shop (Pinedo ch.5.3).

Each operation (i, j) - job j on machine i - is a node. Conjunctive arcs
follow each job's route; each machine's operations form a clique of
disjunctive arc pairs. Selecting one arc per disjunctive pair (a machine
sequence) yields G(D); the selection is feasible iff G(D) has no directed
cycle, and then the makespan is the longest path from source to sink,
with arc lengths equal to the processing time of the operation the arc
leaves (Pinedo Fig. 5.1 and text).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


class CycleError(Exception):
    """The selected disjunctive arcs create a cycle: infeasible schedule."""


@dataclass(frozen=True)
class JobShopInstance:
    """routes[j] = ordered list of (machine, processing_time) for job j."""
    routes: Tuple[Tuple[Tuple[str, int], ...], ...]

    def operations(self) -> List[Tuple[str, int, int]]:
        # (machine, job, processing_time), in route order per job
        return [(m, j, p) for j, route in enumerate(self.routes) for (m, p) in route]


def makespan(instance: JobShopInstance,
             sequences: Dict[str, List[Tuple[int, int]]]) -> Tuple[int, List[Tuple[int, int]]]:
    """Makespan of a machine sequencing, via longest path in G(D).

    sequences[machine] = ordered list of (job, position-in-route) ops on
    that machine. Returns (makespan, critical_operations) where the
    critical operations are one longest source-to-sink chain. Raises
    CycleError if the selection creates a cycle (infeasible).
    """
    ops = []           # index -> (machine, job, p)
    key = {}
    for j, route in enumerate(instance.routes):
        for pos, (m, p) in enumerate(route):
            key[(m, j)] = len(ops)
            key[(j, pos)] = key[(m, j)]
            ops.append((m, j, p))
    n = len(ops)
    arcs: Dict[int, List[int]] = {i: [] for i in range(n)}
    # conjunctive arcs: consecutive operations of each job
    for j, route in enumerate(instance.routes):
        for pos in range(len(route) - 1):
            arcs[key[(j, pos)]].append(key[(j, pos + 1)])
    # disjunctive arcs: machine sequences
    for m, seq in sequences.items():
        ids = []
        for (j, pos) in seq:
            if key.get((j, pos)) is None or ops[key[(j, pos)]][0] != m:
                raise ValueError(f"operation {(j, pos)} is not on machine {m!r}")
            ids.append(key[(j, pos)])
        for a, b in zip(ids, ids[1:]):
            arcs[a].append(b)

    # longest path in DAG (topological order; cycle -> CycleError)
    indeg = [0] * n
    for a in range(n):
        for b in arcs[a]:
            indeg[b] += 1
    order, ready = [], [i for i in range(n) if indeg[i] == 0]
    while ready:
        a = ready.pop()
        order.append(a)
        for b in arcs[a]:
            indeg[b] -= 1
            if indeg[b] == 0:
                ready.append(b)
    if len(order) != n:
        raise CycleError("selected disjunctive arcs contain a cycle")

    dist = [0] * n     # earliest start of each operation
    prev = [-1] * n
    for a in order:
        for b in arcs[a]:
            cand = dist[a] + ops[a][2]
            if cand > dist[b]:
                dist[b] = cand
                prev[b] = a
    cmax = 0
    last = -1
    for a in range(n):
        if dist[a] + ops[a][2] > cmax:
            cmax = dist[a] + ops[a][2]
            last = a
    chain = []
    while last != -1:
        m, j, p = ops[last]
        chain.append((j, m, dist[last], dist[last] + p))
        last = prev[last]
    chain.reverse()
    return cmax, chain
