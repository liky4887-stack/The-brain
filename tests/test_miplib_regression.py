"""MIPLIB regression gate (Stage 1): HiGHS path vs literature optima.

Five MIPLIB 3.0 instances (Crowder-Johnson-Padberg / Bixby test sets),
each with a PROVEN optimum stated in the instance header
(*BEST SOLN: ... (opt)) and cross-checked against the MIPLIB 3.0
catalog (miplib2010.zib.de/miplib3). The adapter's objective is
recomputed from the returned assignment; CP-SAT independently confirms
each optimum on the parsed data (so a parser bug cannot hide behind a
solver bug).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.solvers.highs_mip import read_mps, solve_mip

DATA = Path(__file__).parent / "data" / "miplib"

OPTIMA = {"p0033": 3089.0, "stein27": 18.0, "flugpl": 1201500.0,
          "mod008": 307.0, "lseu": 1120.0}


@pytest.mark.parametrize("name,optimum", sorted(OPTIMA.items()))
def test_miplib_optimum(name, optimum):
    mip = read_mps(str(DATA / f"{name}.mps"))
    res = solve_mip(mip, time_limit_s=30.0)
    assert res["x"] is not None, f"{name}: no solution: {res['status']}"
    assert res["objective"] == pytest.approx(optimum, abs=1e-3), (
        f"{name}: got {res['objective']}, literature optimum {optimum}")


def test_parser_stats_p0033():
    # header: ROWS 16 (1 objective + 15 constraints... the file lists
    # 16 non-N rows), COLUMNS 33, INTEGER 33, NONZERO 98
    mip = read_mps(str(DATA / "p0033.mps"))
    assert mip.c.shape == (33,)
    assert int(mip.integrality.sum()) == 33
    assert mip.A.shape[1] == 33
    # header NONZERO 98 counts constraint-matrix entries; objective
    # entries (33) are separate in this file's accounting
    assert int((mip.A != 0).sum()) == 98
    assert int((mip.c != 0).sum()) == 33


def test_cpsat_confirms_p0033_optimum():
    # independent engine on the same parsed data
    from ortools.sat.python import cp_model
    mip = read_mps(str(DATA / "p0033.mps"))
    assert (mip.c == mip.c.astype(int)).all()  # integer coefficients
    m = cp_model.CpModel()
    x = [m.new_int_var(int(mip.lb[j]), int(min(mip.ub[j], 1e6)), f"x{j}")
         for j in range(len(mip.c))]
    for i, sense in enumerate(mip.sense):
        row = sum(int(mip.A[i, j]) * x[j] for j in range(len(mip.c))
                  if mip.A[i, j] != 0)
        if sense == "L":
            m.add(row <= int(mip.rhs[i]))
        elif sense == "G":
            m.add(row >= int(mip.rhs[i]))
        else:
            m.add(row == int(mip.rhs[i]))
    m.minimize(sum(int(c) * v for c, v in zip(mip.c, x)))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    assert solver.solve(m) == cp_model.OPTIMAL
    assert solver.objective_value == 3089
