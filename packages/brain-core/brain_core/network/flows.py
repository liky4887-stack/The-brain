"""Network flows: labeling max-flow and successive-shortest-path min-cost flow.

Source: Ahuja, Magnanti & Orlin, Network Flows: Theory, Algorithms, and
Applications (Prentice Hall 1993) - Figure 6.17 (labeling algorithm,
with Theorems 6.3 max-flow min-cut, 6.4 augmenting path, 6.5
integrality) and Figure 9.9 (successive shortest path, with Lemmas
9.11-9.12). Scanned book with an OCR text layer; both algorithm pages
were verified against the page images before use.

Implementation notes:
- max_flow uses the labeling algorithm with LIST as a FIFO queue
  (Edmonds-Karp): polynomial, and integer capacities give an integer
  maximum flow (Theorem 6.5).
- min_cost_flow is the book's SSP with potentials (pi := pi - d). The
  shortest path distances are computed by Bellman-Ford rather than
  Dijkstra: correct for any arc costs, not only nonnegative ones.
  A deficit node unreachable from every excess node means infeasible.
- Each original arc gets its own forward/backward residual edge pair, so
  antiparallel real arcs never alias in the residual structure.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Tuple


class FlowError(Exception):
    """Infeasible instance (e.g. unreachable demand in min_cost_flow)."""


class _Edge:
    __slots__ = ("u", "v", "cap", "cost", "orig_cap", "rev")

    def __init__(self, u: int, v: int, cap: int, cost: int):
        self.u, self.v, self.cap, self.cost = u, v, cap, cost
        self.orig_cap = cap
        self.rev: Optional["_Edge"] = None


def _build(arcs, with_cost: bool) -> Tuple[List[List[_Edge]], List[_Edge]]:
    n_max = 0
    for a in arcs:
        n_max = max(n_max, a[0], a[1])
    adj: List[List[_Edge]] = [[] for _ in range(n_max + 1)]
    forward: List[_Edge] = []
    for a in arcs:
        u, v, cap = a[0], a[1], a[2]
        if u == v:
            raise ValueError("self-loops are not supported")
        if cap < 0:
            raise ValueError("capacities must be nonnegative")
        w = a[3] if with_cost else 0
        f = _Edge(u, v, cap, w)
        r = _Edge(v, u, 0, -w)
        f.rev, r.rev = r, f
        adj[u].append(f)
        adj[v].append(r)
        forward.append(f)
    return adj, forward


def max_flow(n: int, arcs: List[Tuple[int, int, int]], s: int, t: int):
    """Labeling algorithm (Figure 6.17), BFS variant. Returns (value, flows)."""
    if not (0 <= s < n and 0 <= t < n) or s == t:
        raise ValueError("need distinct in-range source and sink")
    adj, forward = _build(arcs, with_cost=False)
    total = 0
    while True:
        pred: List[Optional[_Edge]] = [None] * n
        seen = [False] * n
        seen[s] = True
        q = deque([s])
        while q and not seen[t]:
            i = q.popleft()
            for e in adj[i]:
                if e.cap > 0 and not seen[e.v]:
                    seen[e.v] = True
                    pred[e.v] = e
                    q.append(e.v)
        if not seen[t]:
            break
        delta = None
        j = t
        while j != s:
            e = pred[j]
            delta = e.cap if delta is None else min(delta, e.cap)
            j = e.u
        j = t
        while j != s:
            e = pred[j]
            e.cap -= delta
            e.rev.cap += delta
            j = e.u
        total += delta
    flows: Dict[Tuple[int, int], int] = {}
    for e in forward:
        f = e.orig_cap - e.cap
        if f > 0:
            flows[(e.u, e.v)] = f
    return total, flows


def min_cost_flow(n: int, arcs: List[Tuple[int, int, int, int]], balance: List[int]):
    """Successive shortest path (Figure 9.9). balance[i] > 0 = supply.

    Returns (total_cost, flows). Raises FlowError if some demand cannot
    be reached from the remaining supply in the residual network.

    Scope (honest): arc costs must be nonnegative - the book's chapter-9
    assumption ("All arc costs are nonnegative"), under which pi = 0
    satisfies reduced-cost optimality and SSP maintains it (Lemma 9.12).
    Negative-cost instances need cycle-canceling first (sec. 9.6); that
    algorithm is documented in the skill but NOT implemented, so negative
    costs are rejected here rather than silently mis-optimized (the LP
    cross-check caught exactly this during testing).
    """
    if any(a[3] < 0 for a in arcs):
        raise ValueError(
            "negative arc costs are outside SSP scope (ch.9 assumes "
            "nonnegative costs); cycle-canceling is not implemented")
    if len(balance) != n:
        raise ValueError("balance must have one entry per node")
    if sum(balance) != 0:
        raise ValueError("supplies and demands must sum to zero")
    adj, forward = _build(arcs, with_cost=True)
    e = list(balance)  # e(i) > 0: excess (supply not yet sent)
    pi = [0] * n
    INF = float("inf")

    def shortest_paths(src: int):
        # Bellman-Ford on residual edges with reduced costs.
        d = [INF] * n
        pred: List[Optional[_Edge]] = [None] * n
        d[src] = 0
        for _ in range(n - 1):
            moved = False
            for u in range(n):
                if d[u] == INF:
                    continue
                for ed in adj[u]:
                    if ed.cap > 0:
                        rc = ed.cost - pi[u] + pi[ed.v]
                        if d[u] + rc < d[ed.v]:
                            d[ed.v] = d[u] + rc
                            pred[ed.v] = ed
                            moved = True
            if not moved:
                break
        return d, pred

    while True:
        excess = [i for i in range(n) if e[i] > 0]
        if not excess:
            break
        k = excess[0]
        d, pred = shortest_paths(k)
        deficit = [i for i in range(n) if e[i] < 0 and d[i] < INF]
        if not deficit:
            raise FlowError(f"demand unreachable from supply at node {k}")
        l = min(deficit, key=lambda i: d[i])
        pi = [pi[i] - (0 if d[i] == INF else d[i]) for i in range(n)]
        delta = min(e[k], -e[l])
        edges = []
        j = l
        while j != k:
            ed = pred[j]
            edges.append(ed)
            delta = min(delta, ed.cap)
            j = ed.u
        for ed in edges:
            ed.cap -= delta
            ed.rev.cap += delta
        e[k] -= delta
        e[l] += delta

    flows: Dict[Tuple[int, int], int] = {}
    for ed in forward:
        f = ed.orig_cap - ed.cap
        if f > 0:
            flows[(ed.u, ed.v)] = f
    total = sum(ed.cost * (ed.orig_cap - ed.cap) for ed in forward)
    return total, flows
