"""Routing: CVRP via PyVRP (Stage 4, slice 5).

PyVRP (MIT license - checked 2026-11-25, recorded in DECISIONS.md)
solves the capacitated VRP with a hybrid genetic search. This module
is a thin honest wrapper: instances come from VRPLIB text, costs are
read back from the returned solution's own routes (recomputed from
the distance matrix), and gaps against best-known solutions are
measured, never asserted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class CvrpInstance:
    name: str
    capacity: float
    depot: tuple[float, float]
    customers: list[tuple[float, float, float]]   # (x, y, demand)

    @property
    def coords(self):
        return [self.depot] + [(x, y) for x, y, _ in self.customers]


def read_vrplib(path: str) -> CvrpInstance:
    """Minimal VRPLIB reader (EUC_2D, DEPOT_SECTION = node 1)."""
    name = cap = None
    coords: dict[int, tuple[float, float]] = {}
    demands: dict[int, float] = {}
    section = None
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line == "EOF":
                continue
            if line.startswith("NAME"):
                name = line.split(":")[1].strip()
            elif line.startswith("CAPACITY"):
                cap = float(line.split(":")[1].strip())
            elif line == "NODE_COORD_SECTION":
                section = "coord"
            elif line == "DEMAND_SECTION":
                section = "demand"
            elif line == "DEPOT_SECTION":
                section = "depot"
            elif section == "coord":
                i, x, y = line.split()
                coords[int(i)] = (float(x), float(y))
            elif section == "demand":
                i, d = line.split()
                demands[int(i)] = float(d)
            elif section == "depot":
                pass                        # depot is node 1
    depot = coords[1]
    customers = [(coords[i][0], coords[i][1], demands[i])
                 for i in sorted(coords) if i != 1]
    return CvrpInstance(name or path, cap, depot, customers)


def dist_matrix(inst: CvrpInstance) -> list[list[int]]:
    """CVRPLIB EUC_2D convention: nint (rounded) Euclidean."""
    pts = inst.coords
    n = len(pts)
    return [[int(math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)
                 + 0.5)
             for b in pts] for a in pts]


@dataclass
class CvrpResult:
    cost: int                       # recomputed from routes + matrix
    routes: list[list[int]]         # customer indices (1-based in
                                    # the instance's node numbering)
    wall_s: float


def solve_cvrp(inst: CvrpInstance, max_runtime_s: float = 30.0,
               seed: int = 0, max_vehicles: int | None = None
               ) -> CvrpResult:
    """Solve with PyVRP; the reported cost is recomputed from the
    returned routes on the rounded Euclidean matrix (CVRPLIB
    convention), not read from solver internals."""
    import time

    from pyvrp import Model
    from pyvrp.stop import MaxRuntime

    m = Model()
    m.add_vehicle_type(
        num_available=max_vehicles or len(inst.customers),
        capacity=int(inst.capacity))
    depot = m.add_depot(x=int(inst.depot[0]), y=int(inst.depot[1]))
    clients = [m.add_client(x=int(x), y=int(y), delivery=int(d))
               for x, y, d in inst.customers]
    D = dist_matrix(inst)
    locs = [depot] + clients
    for i, fi in enumerate(locs):
        for j, tj in enumerate(locs):
            m.add_edge(fi, tj, distance=D[i][j])
    t0 = time.monotonic()
    res = m.solve(stop=MaxRuntime(max_runtime_s), seed=seed,
                  display=False)
    wall = time.monotonic() - t0
    best = res.best
    routes = [list(r.visits()) for r in best.routes()]  # 1-based client nodes
    cost = 0
    for r in routes:
        path = [0] + r + [0]
        cost += sum(D[a][b] for a, b in zip(path, path[1:]))
    return CvrpResult(cost=cost, routes=routes, wall_s=wall)


def gap_to_bks(cost: float, bks: float) -> float:
    """Measured relative gap to a best-known solution."""
    return (cost - bks) / bks
