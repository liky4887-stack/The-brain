"""Critical Path Method: forward and backward procedures.

Source: Pinedo, Planning and Scheduling in Manufacturing and Services
(Springer), Algorithms 4.2.1 and 4.2.2 - digital text, no OCR.

Forward: earliest start S'_j = max over predecessors k of C'_k,
C'_j = S'_j + p_j; makespan = max C'_j. Backward from Cmax:
C''_j = min over successors k of S''_k, S''_j = C''_j - p_j.
Slack (float) = S''_j - S'_j; critical jobs have zero slack and form one
or more critical paths from time 0 to Cmax.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set


@dataclass(frozen=True)
class CPMResult:
    earliest_start: Dict[str, int]
    earliest_finish: Dict[str, int]
    latest_start: Dict[str, int]
    latest_finish: Dict[str, int]
    makespan: int
    slack: Dict[str, int]
    critical: List[str]


def cpm(processing: Dict[str, int], predecessors: Dict[str, Set[str]]) -> CPMResult:
    """Forward/backward pass. Raises ValueError on a cyclic precedence graph."""
    for j in processing:
        if processing[j] < 0:
            raise ValueError(f"negative processing time for {j}")
        predecessors.setdefault(j, set())
    # topological order (Kahn); a leftover node means a cycle
    indeg = {j: 0 for j in processing}
    for j in processing:
        for k in predecessors[j]:
            if k not in processing:
                raise ValueError(f"unknown predecessor {k!r} of {j!r}")
            indeg[j] += 1
    order = []
    ready = sorted([j for j in processing if indeg[j] == 0])
    succ = {j: set() for j in processing}
    for j in processing:
        for k in predecessors[j]:
            succ[k].add(j)
    while ready:
        j = ready.pop(0)
        order.append(j)
        for k in sorted(succ[j]):
            indeg[k] -= 1
            if indeg[k] == 0:
                ready.append(k)
    if len(order) != len(processing):
        raise ValueError("precedence graph has a cycle")

    es, ef = {}, {}
    for j in order:
        es[j] = max((ef[k] for k in predecessors[j]), default=0)
        ef[j] = es[j] + processing[j]
    cmax = max(ef.values(), default=0)
    lf, ls = {}, {}
    for j in reversed(order):
        lf[j] = min((ls[k] for k in succ[j]), default=cmax)
        ls[j] = lf[j] - processing[j]
    slack = {j: ls[j] - es[j] for j in processing}
    return CPMResult(
        earliest_start=es, earliest_finish=ef,
        latest_start=ls, latest_finish=lf,
        makespan=cmax, slack=slack,
        critical=sorted([j for j in processing if slack[j] == 0]),
    )
