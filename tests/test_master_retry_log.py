"""Every HiGHS attempt of the CG master (default, ipm, ds) is logged with
the master size; before, the middle attempt and the size were lost."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "packages" / "brain-core"))
from brain_core.rolling import coupled_dw as D  # noqa: E402
import scipy.optimize as so  # noqa: E402

COLS = [[{"cost": 5.0, "mat": {"m": 1.0}, "lab": {}}],
        [{"cost": 7.0, "mat": {"m": 1.0}, "lab": {}}]]


def _fake(statuses, real):
    calls = iter(statuses)

    def f(*a, **k):
        st = next(calls)
        if st == 0:
            return real(*a, **k)
        return SimpleNamespace(status=st, message=f"msg-{k['method']}")
    return f


def test_all_three_attempts_and_size_are_in_the_failure(monkeypatch):
    monkeypatch.setattr(so, "linprog", _fake([4, 4, 4], so.linprog))
    out = D._solve_master(COLS, ["m"], [10.0])
    assert out[0] is None
    st = out[4]
    for m in ("highs:", "highs-ipm:", "highs-ds:", "msg-highs-ipm"):
        assert m in st, st
    assert "3 rows" in st and "real columns" in st, st


def test_success_after_retry_logs_the_failed_attempts(monkeypatch):
    monkeypatch.setattr(so, "linprog", _fake([4, 0], so.linprog))
    out = D._solve_master(COLS, ["m"], [10.0])
    assert out[0] is not None and "highs:" in out[4] \
        and "highs-ipm:" in out[4] and "rows" in out[4], out[4]


def test_clean_solve_status_unchanged():
    assert D._solve_master(COLS, ["m"], [10.0])[4] == "optimal"
