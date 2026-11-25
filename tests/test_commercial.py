"""Stage 4, slice 8: the commercial pass-through is honest.

No commercial binding here: UNAVAILABLE, never a silent substitute.
With a fake adapter registered, the objective is RECOMPUTED from x
(the adapter's claimed objective is ignored) and a malformed x is
rejected.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.solvers.commercial import (available_solvers,
                                           register_adapter,
                                           solve_mip_commercial)
from brain_core.solvers.highs_mip import MIP


def _mip():
    # min 2*x0 + 3*x1 s.t. x0 + x1 >= 1, 0 <= x <= 1 continuous
    return MIP("t", np.array([2.0, 3.0]),
               np.array([[1.0, 1.0]]), ("G",), np.array([1.0]),
               np.zeros(2), np.ones(2), np.zeros(2))


def test_unavailable_without_adapter():
    res = solve_mip_commercial(_mip(), "gurobi")
    assert res["x"] is None
    assert "UNAVAILABLE" in res["status"]
    assert "gurobi" in res["status"]


def test_adapter_objective_recomputed_not_trusted():
    def fake(mip, time_limit_s, mip_rel_gap):
        # optimal: x0=1, x1=0 -> true objective 2; CLAIM 0 (a lie)
        return {"status": "OPTIMAL", "objective": 0.0,
                "x": np.array([1.0, 0.0])}
    register_adapter("fake-opt", fake)
    assert "fake-opt" in available_solvers()
    res = solve_mip_commercial(_mip(), "fake-opt")
    assert res["objective"] == 2.0         # recomputed, not 0.0


def test_adapter_malformed_x_rejected():
    register_adapter("fake-bad",
                     lambda mip, **kw: {"status": "OK",
                                        "x": np.array([1.0])})
    res = solve_mip_commercial(_mip(), "fake-bad")
    assert res["x"] is None
    assert "ERROR" in res["status"]
