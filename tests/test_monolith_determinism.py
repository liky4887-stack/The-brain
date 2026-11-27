"""Monolith (highspy, 1 thread) twice on the same MIP: same objective, same
solution vector, same node count, with and without the (l,S) cuts. These are
COVERAGE tests on tiny instances (3 lines, 3 SKUs, 3 days, seeds 1-3, limit
60 s, rel_gap 0, threads 1); they say nothing about the large runs, which
are time-limited and therefore not deterministic by construction."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_monolith_probe_fix import _tiny  # noqa: E402
import monolith_scaling as ms  # noqa: E402


def _sig(r):
    return (r["status"], r["objective"], tuple(np.round(r["x"], 9)),
            r["node_count"])


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_monolith_twice_is_identical(seed):
    f, hs, mip, meta = _tiny(seed)
    cut, n_ls = ms.add_ls_cuts(mip, meta, [f], hs, 3)
    assert n_ls > 0
    for label, m in (("plain", mip), ("ls-cuts", cut)):
        a = ms.solve_highspy(m, 60, 1, rel_gap=0.0)
        b = ms.solve_highspy(m, 60, 1, rel_gap=0.0)
        assert a["x"] is not None and b["x"] is not None, label
        assert _sig(a) == _sig(b), (label, a["objective"], b["objective"],
                                    a["node_count"], b["node_count"])
