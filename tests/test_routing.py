"""Stage 4, slice 5: CVRP routing via PyVRP.

Small-instance checks in the suite; the CVRPLIB X gate is
benchmark-marked. Costs are recomputed from returned routes on the
rounded Euclidean matrix (CVRPLIB convention).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.routing import (CvrpInstance, dist_matrix, gap_to_bks,
                                solve_cvrp)

BKS_X_N101_K25 = 27591     # CVRPLIB page (optimal), fetched 2026-11-25


def test_triangle_instance_exact():
    """4 customers on a unit square, capacity forces 2 routes."""
    inst = CvrpInstance("tiny", 2.0, (0.0, 0.0),
                        [(1.0, 0.0, 1.0), (0.0, 1.0, 1.0),
                         (-1.0, 0.0, 1.0), (0.0, -1.0, 1.0)])
    res = solve_cvrp(inst, max_runtime_s=2, seed=1)
    # capacity 2 -> 2 routes; each route serves 2 customers
    assert len(res.routes) == 2
    assert sorted(sum(res.routes, [])) == [1, 2, 3, 4]
    # cost recomputed: each customer is 1 from depot; adjacent
    # customers 1 apart -> 1+1+1 per route = 6 total
    assert res.cost == 6


def test_gap_measured_not_asserted():
    assert gap_to_bks(27600, 27591) == pytest.approx(9 / 27591)


@pytest.mark.benchmark
def test_cvrplib_x_gate_within_1pct_of_bks():
    """Stage 4 gate: X-n101-k25 within 1% of the BKS (27,591)."""
    inst_path = Path("/tmp/X-n101-k25.vrp")
    if not inst_path.exists():
        pytest.skip("instance file not downloaded")
    from brain_core.routing import read_vrplib
    inst = read_vrplib(str(inst_path))
    res = solve_cvrp(inst, max_runtime_s=60, seed=0)
    gap = gap_to_bks(res.cost, BKS_X_N101_K25)
    print(f"X-n101-k25: cost {res.cost} vs BKS {BKS_X_N101_K25} "
          f"(gap {100 * gap:.3f}%, wall {res.wall_s:.0f}s, "
          f"{len(res.routes)} routes)")
    assert gap <= 0.01
