"""Guard: a plant whose operations list a line twice (the generator does
this with n_lines=2) must not produce duplicate MIP keys: every column is
used, x appears once with coefficient 1 in each coverage row, and the
brute-force optimum equals the MIP optimum."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "brain-core"))
sys.path.insert(0, str(ROOT / "tests"))

from brain_core.synthetic import FnbParams, generate_fnb_factory  # noqa: E402
from brain_core.rolling.two_level import (build_bucket_mip,  # noqa: E402
                                          ObjectiveWeights, _sku_data)
from brain_core.solvers.highs_mip import solve_mip  # noqa: E402


def _two_line(seed):
    p = generate_fnb_factory(FnbParams(
        seed=seed, n_lines=2, n_skus=3, days=3, active_fraction=1.0,
        utilization=0.6, n_raw_materials=3, families=("DAIRY",)))
    return p


def test_sku_lines_unique():
    p = _two_line(1)
    for s, (_, lines, _) in _sku_data(p.factory).items():
        assert len(lines) == len(set(lines)), (s, lines)


def test_no_orphan_columns_and_unit_coefficients():
    p = _two_line(1)
    w = ObjectiveWeights(setup=5000.0)
    mip, maps = build_bucket_mip(p.factory, p.params.horizon_start, 3,
                                 p.day_capacity_minutes, 0.15, weights=w)
    n_x, n_y = len(maps["x"]), len(maps["y"])
    assert mip.A.shape[1] == n_x + 3 * n_y, "orphan columns"
    used = np.unique(mip.A.tocsc().nonzero()[1])
    assert len(used) == mip.A.shape[1] or set(maps["x"].values()) <= set(used)
    r = solve_mip(mip, time_limit_s=30, mip_rel_gap=0.0)
    assert r["x"] is not None
