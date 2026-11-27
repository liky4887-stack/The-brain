"""Same input twice gives the same plan (no hidden randomness)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_decompose import H0, _solvable_two_cell_factory
from brain_core.rolling.two_level import solve_window


def _sig(plan):
    return sorted((a.line, a.day, a.seq_pos, a.sku, round(a.qty, 6))
                  for a in plan.assignments), \
        plan.bucket.objective


def test_solve_window_is_deterministic():
    f = _solvable_two_cell_factory()
    runs = [solve_window(f, H0, 2, 480.0, bucket_time_s=5, seq_time_s=2)
            for _ in range(2)]
    assert _sig(runs[0]) == _sig(runs[1])


def test_column_generation_is_deterministic():
    """CG twice on the same binding-caps instance: same iterations,
    same column counts, same LB and UB to the last digit. A drift here
    means hidden randomness (thread races, dict order, time limits
    that bind) and makes every CG number non-reproducible."""
    from test_coupled_dw import _two_plants, _uncoupled
    from brain_core.rolling.coupled_dw import (column_generation,
                                               integer_master)
    ps, hs, cap, days = _two_plants()
    _solo, mat_tot = _uncoupled(ps, hs, cap, days)
    caps = {k: 0.75 * v for k, v in mat_tot.items()}

    def sig():
        dw = column_generation([p.factory for p in ps], hs, days, cap,
                               supplier_cap=caps, max_iter=40,
                               time_limit_s=30.0)
        dw = integer_master(dw, [p.factory for p in ps], hs, days)
        return (dw.iterations, tuple(dw.columns_per_plant),
                dw.converged, dw.lower_bound, dw.upper_bound,
                tuple(p for p in dw.problems if "invariant" in p))

    a, b = sig(), sig()
    assert a == b, (a, b)
    assert not a[-1], a[-1]          # no invariant findings either


def test_solve_decomposed_is_deterministic():
    """The parallel path: cells finish in any order, the merged plan
    must not depend on it."""
    from brain_core.decompose import solve_decomposed
    f = _solvable_two_cell_factory()
    runs = [solve_decomposed(f, H0, days=2, cap_min=480.0,
                             bucket_time_s=5, seq_time_s=2)
            for _ in range(2)]
    assert _sig(runs[0].plan) == _sig(runs[1].plan)
