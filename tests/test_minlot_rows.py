"""Min-lot rows in the monolith (add_min_lot), tiny instances (3 lines,
3 SKUs, 3 days), highspy 1 thread, rel_gap 0, frac 0.6 of the model's big-M.
Measured before writing: on seeds 2 and 4 the plan WITHOUT the rows has
min-lot violations (2 and 2) and the plan WITH the rows has 0, at a higher
objective. This is a coverage test of the rows on these instances; the
violation counter is the model's own (lots dict), the independent
benchmarks/minlot_check.py uses a different lot definition."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_monolith_probe_fix import _tiny  # noqa: E402
import monolith_scaling as ms  # noqa: E402


def _viol(meta, r, lots):
    q = [{k: r["x"][j] for k, j in meta["maps"][0]["x"].items()}]
    return ms.min_lot_violations(q, lots)


@pytest.mark.parametrize("seed", [2, 4])
def test_min_lot_rows_remove_short_runs_and_cost_more(seed):
    f, hs, mip, meta = _tiny(seed)
    ml, lots = ms.add_min_lot(mip, meta, 0.6)
    assert lots and ml.A.shape[0] == mip.A.shape[0] + len(lots)
    free = ms.solve_highspy(mip, 60, 1, rel_gap=0.0)
    held = ms.solve_highspy(ml, 60, 1, rel_gap=0.0)
    assert free["x"] is not None and held["x"] is not None
    assert len(_viol(meta, free, lots)) > 0, "control: rows must matter"
    assert _viol(meta, held, lots) == []
    assert held["objective"] >= free["objective"] - 1e-6
