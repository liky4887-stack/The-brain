"""coupled_comparison: the monolith, the CG and the integer master are all
solved with the same weights, passed explicitly, and the row records them.
Fail-before: no weights were passed (solver defaults) and the row did not
say. Real n=2 run with spies that call through (monolith limit 3 s, 2 CG
iterations)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "packages" / "brain-core"))
import coupled_comparison as cc  # noqa: E402


def test_same_weights_everywhere_and_recorded(monkeypatch):
    seen = {}

    def spy(name):
        real = getattr(cc, name)

        def f(*a, **k):
            seen[name] = k.get("weights")
            return real(*a, **k)
        monkeypatch.setattr(cc, name, f)

    for n in ("build_coupled_mip", "column_generation", "integer_master"):
        spy(n)
    monkeypatch.setenv("CMP_CG_ITERS", "2")
    monkeypatch.setenv("CMP_LR_ROUNDS", "1")
    row = cc.run(2, monolith_limit_s=3.0)
    assert set(seen) == {"build_coupled_mip", "column_generation",
                         "integer_master"}
    assert all(w is cc.WEIGHTS for w in seen.values()), seen
    from brain_core.rolling.two_level import DEFAULT_WEIGHTS
    assert cc.WEIGHTS == DEFAULT_WEIGHTS   # the Lagrangian path uses these
    assert "weights_note" in row["lagrangian"]
    assert row["weights"] == {"setup": 50.0, "late": 1000.0,
                              "early": 0.001, "energy": 0.0}
