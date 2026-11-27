"""CG master numerics. Fixture: the master at pools 0.9 seed_base 0 iteration
178 (main 6a55e4a) on which HiGHS default, ipm and ds all returned Status 15
(model_status Unknown) with BIGM 1e12 next to column costs up to 1.3e9."""
import ast
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "packages" / "brain-core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from brain_core.rolling import coupled_dw as D  # noqa: E402


def _fixture():
    d = json.load(gzip.open(Path(__file__).parent / "fixtures"
                            / "master_status15.json.gz", "rt"))
    dec = lambda m: {ast.literal_eval(k): v for k, v in m.items()}  # noqa: E731
    cs = [[{"cost": c["cost"], "mat": dec(c["mat"]), "lab": dec(c["lab"])}
           for c in p] for p in d["colsets"]]
    return cs, [ast.literal_eval(p) for p in d["pools"]], d["caps"]


def test_status15_master_now_solves_with_zero_artificials():
    cs, pools, caps = _fixture()
    obj, u, sigma, art, st, lam = D._solve_master(cs, pools, caps)
    assert obj is not None and st == "optimal", st
    assert art == 0.0
    assert abs(obj - 131266872.51616867) <= 1e-6 * obj


def test_unscaled_master_fails_as_on_main(monkeypatch):
    """Fail-before: scale 1.0 reproduces the Status 15 failure."""
    monkeypatch.setattr(D, "MASTER_COST_SCALE", 1.0)
    cs, pools, caps = _fixture()
    obj, *_r, st, _lam = D._solve_master(cs, pools, caps)
    assert obj is None and "Status 15" in st, st


def test_scaling_does_not_change_duals_or_objective(monkeypatch):
    cs, pools, caps = _fixture()
    a = D._solve_master(cs, pools, caps)
    # a feasible easier master: drop cost magnitude so both scales solve
    cs2 = [[dict(c, cost=c["cost"] * 1e-3) for c in p] for p in cs]
    monkeypatch.setattr(D, "BIGM", 1e9)
    b1 = D._solve_master(cs2, pools, caps)
    monkeypatch.setattr(D, "MASTER_COST_SCALE", 1.0)
    b2 = D._solve_master(cs2, pools, caps)
    assert b1[0] is not None and b2[0] is not None
    assert abs(b1[0] - b2[0]) <= 1e-7 * abs(b2[0])
    import numpy as np
    assert np.allclose(b1[1], b2[1], rtol=1e-5, atol=1e-3)
    assert a[0] is not None


def test_cheap_regime_scale_follows_data():
    """Costs ~1e3 (cheap regime): the data-derived scale keeps the master
    solvable and the objective is exactly the expensive one times the factor."""
    cs, pools, caps = _fixture()
    f = 1e-6
    cs2 = [[dict(c, cost=c["cost"] * f) for c in p] for p in cs]
    obj, _u, _s, art, st, _lam = D._solve_master(cs2, pools, caps)
    assert st == "optimal" and art == 0.0, (st, art)
    assert abs(obj - 131266872.51616867 * f) <= 1e-6 * obj
