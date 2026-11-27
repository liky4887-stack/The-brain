import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain_core.guards.progress import FlatProgress
from test_coupled_dw import _two_plants, _uncoupled


def test_flat_progress_catches_flat_and_not_improving():
    f = FlatProgress(3, 1e-6, maximise=True)
    assert [f.update(v) for v in (1, 2, 3)] == [False] * 3
    assert [f.update(3.0) for _ in range(3)] == [False, False, True]
    assert "flat" in f.reason()


def test_gap_regression_counts_as_no_progress():
    f = FlatProgress(2, 1e-6, maximise=False)
    assert [f.update(v) for v in (0.5, 0.4, 0.45, 0.5)] == \
        [False, False, False, True]


def test_cg_progress_guard_stops_named_when_flat():
    from brain_core.rolling.coupled_dw import column_generation
    ps, hs, cap, days = _two_plants()
    solo, mat_tot = _uncoupled(ps, hs, cap, days)
    caps = {k: 0.75 * v for k, v in mat_tot.items()}
    base = column_generation([p.factory for p in ps], hs, days, cap,
                             supplier_cap=caps, max_iter=40,
                             time_limit_s=30.0)
    assert base.iterations > 2, base.iterations   # fixture needs >2
    dw = column_generation([p.factory for p in ps], hs, days, cap,
                           supplier_cap=caps, max_iter=40,
                           time_limit_s=30.0, progress_window=1,
                           progress_rel_tol=10.0)
    assert dw.status == "stalled: bound flat (progress guard)"
    assert any("flat" in p for p in dw.problems)
    assert not dw.converged
    assert dw.iterations < base.iterations


def test_cg_default_unchanged_without_guard():
    from brain_core.rolling.coupled_dw import column_generation
    ps, hs, cap, days = _two_plants()
    solo, mat_tot = _uncoupled(ps, hs, cap, days)
    caps = {k: 2.0 * v for k, v in mat_tot.items()}
    dw = column_generation([p.factory for p in ps], hs, days, cap,
                           supplier_cap=caps, max_iter=40,
                           time_limit_s=30.0)
    assert dw.converged
