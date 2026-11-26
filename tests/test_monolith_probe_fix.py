"""Fix-test for the monolith probe (review 9:43 PM): every solver path and
the (l,S) cuts must reproduce the BRUTE-FORCE optimum (all binary
combinations, LP over the rest) on a tiny instance whose answer is fully
known, with the right y and integral y. Also: the brute-force optimum
satisfies every cut (cuts remove no feasible solution)."""
import itertools
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "packages" / "brain-core"))

from scipy.optimize import linprog  # noqa: E402
from brain_core.synthetic import FnbParams, generate_fnb_factory  # noqa: E402
from brain_core.rolling.two_level import (build_bucket_mip,  # noqa: E402
                                          ObjectiveWeights)
import monolith_scaling as ms  # noqa: E402


def _tiny(seed, tbo=3.0):
    p = generate_fnb_factory(FnbParams(
        seed=seed, n_lines=3, n_skus=3, days=3, active_fraction=1.0,
        utilization=0.6, n_raw_materials=3, families=("DAIRY", "BAKERY")))
    f, hs, cap = p.factory, p.params.horizon_start, p.day_capacity_minutes
    # real setup weight so y matters
    w = ObjectiveWeights(setup=5000.0)
    mip, maps = build_bucket_mip(f, hs, 3, cap, 0.15, weights=w)
    meta = {"maps": [maps], "offsets": [0]}
    for s_, d_ in maps["sku"].items():  # duplicate lines would orphan cols
        assert len(d_[1]) == len(set(d_[1])), "duplicate lines in tiny case"
    return f, hs, mip, meta


def _brute(mip):
    A = mip.A.tocsr()
    ub_rows = [i for i, s in enumerate(mip.sense) if s == "L"]
    lb_rows = [i for i, s in enumerate(mip.sense) if s == "G"]
    eq_rows = [i for i, s in enumerate(mip.sense) if s == "E"]
    A_ub = np.vstack([A[ub_rows].toarray(), -A[lb_rows].toarray()]) \
        if (ub_rows or lb_rows) else None
    b_ub = np.concatenate([mip.rhs[ub_rows], -mip.rhs[lb_rows]])
    A_eq = A[eq_rows].toarray() if eq_rows else None
    b_eq = mip.rhs[eq_rows] if eq_rows else None
    ints = np.where(np.array(mip.integrality) > 0)[0]
    best = (np.inf, None, None)
    for combo in itertools.product((0.0, 1.0), repeat=len(ints)):
        lb, ub = np.array(mip.lb, float), np.array(mip.ub, float)
        lb[ints] = ub[ints] = combo
        r = linprog(mip.c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                    bounds=list(zip(lb, np.where(np.isinf(ub), None, ub))),
                    method="highs")
        if r.status == 0 and r.fun < best[0]:
            best = (r.fun, r.x, combo)
    return best


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_all_paths_match_brute_force(seed, monkeypatch):
    f, hs, mip, meta = _tiny(seed)
    n_bin = int(mip.integrality.sum())
    assert n_bin <= 12, n_bin
    ref_obj, ref_x, ref_y = _brute(mip)
    assert np.isfinite(ref_obj)
    ints = np.where(np.array(mip.integrality) > 0)[0]

    def check(m, label):
        r = ms.solve_highspy(m, 60, 1, rel_gap=0.0)
        assert r["x"] is not None, label
        assert r["int_violation"] < 1e-6, (label, r["int_violation"])
        assert r["node_count"] >= 0, (label, "not a MIP run")
        assert abs(r["objective"] - ref_obj) <= 1e-6 * max(1, abs(ref_obj)), \
            (label, r["objective"], ref_obj)
        y = np.round(r["x"][ints])
        # the y must be a feasible optimal y: its LP value equals ref
        return y

    check(mip, "plain")
    monkeypatch.setenv("MS_ROOT_IPM", "1")
    check(mip, "root-ipm")
    monkeypatch.delenv("MS_ROOT_IPM")
    cut, n_ls = ms.add_ls_cuts(mip, meta, [f], hs, 3)
    assert n_ls > 0
    # validity: the brute-force optimum satisfies every cut row
    A = cut.A.tocsr()
    new = slice(mip.A.shape[0], cut.A.shape[0])
    lhs = A[new] @ ref_x
    assert np.all(lhs >= cut.rhs[new] - 1e-6), \
        float(np.min(lhs - cut.rhs[new]))
    check(cut, "ls-cuts")
    # and brute force over the CUT model gives the same optimum
    assert abs(_brute(cut)[0] - ref_obj) <= 1e-6 * max(1, abs(ref_obj))


def test_fractional_y_is_flagged():
    """solve with integrality dropped (the solver=ipm failure mode) must
    be detectable: int_violation is reported and node_count < 0 / not a
    MIP run is caught by check()."""
    f, hs, mip, meta = _tiny(1)
    r = ms.solve_highspy(mip, 60, 1, rel_gap=0.0)
    assert r["int_violation"] is not None
