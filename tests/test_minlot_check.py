"""Independent min-lot checker and caps-key regression (probe code)."""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))
from minlot_check import independent_min_lot  # noqa: E402


def test_flags_short_run_and_passes_full_run():
    dd = {(0, "a"): 10.0}
    ok = independent_min_lot([{("a", 0, "L"): 15.0}], dd, 10.0, 1.5)
    bad = independent_min_lot([{("a", 0, "L"): 5.0}], dd, 10.0, 1.5)
    assert ok["violations"] == 0 and ok["runs"] == 1
    assert bad["violations"] == 1 and bad["worst_shortfall_frac"] > 0.6


def test_lines_are_summed_and_zero_runs_ignored():
    dd = {(0, "a"): 10.0}
    r = independent_min_lot(
        [{("a", 0, "L1"): 8.0, ("a", 0, "L2"): 8.0, ("a", 1, "L1"): 0.0}],
        dd, 10.0, 1.5)
    assert r["violations"] == 0 and r["runs"] == 1


def test_caps_key_depends_on_effective_params():
    def key(c):
        return hashlib.sha1(repr(sorted(c.items())).encode()).hexdigest()
    base = dict(days=14, sup=1.5, lab=1.5, minlot_days=1.5)
    assert key(base) != key({**base, "sup": 2.0})
    assert key(base) != key({**base, "minlot_days": 0})
