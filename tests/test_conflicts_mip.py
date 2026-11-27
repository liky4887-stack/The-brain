"""Family-level infeasibility explanation for MIPs: named families, amounts, minimality."""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))
from brain_core.solvers.highs_mip import MIP, explain_infeasible_mip, _milp_feasible  # noqa: E402


def _mip(A, sense, rhs, fam, integ=None):
    n = len(A[0])
    return MIP("t", np.zeros(n), np.array(A, float), tuple(sense), np.array(rhs, float),
               np.zeros(n), np.full(n, np.inf),
               np.array(integ if integ is not None else [0] * n), tuple(fam))


def test_capacity_vs_demand_names_both_families_with_amount():
    # x1 + x2 <= 10 (capacity), x1 + x2 >= 14 (demand): 4 missing.
    # A third, unrelated family must not be named.
    m = _mip([[1, 1], [1, 1], [1, 0]], "LGL", [10, 14, 100], ["capacity", "demand", "other"])
    r = explain_infeasible_mip(m)
    assert r["level"] == "family"
    assert r["minimal_families"] == ["capacity", "demand"], r
    assert abs(sum(r["slack_by_family"].values()) - 4.0) < 1e-6, r
    assert "other" not in r["slack_by_family"]


def test_minimality_dropping_either_family_is_feasible():
    m = _mip([[1, 1], [1, 1], [1, 0]], "LGL", [10, 14, 100], ["capacity", "demand", "other"])
    fam = np.array(m.row_family)
    for drop in ("capacity", "demand"):
        assert _milp_feasible(m, fam != drop, 10.0) is True


def test_integer_infeasibility_is_found():
    # 2x = 3 with x integer: LP-feasible, MIP-infeasible
    m = _mip([[2]], "E", [3], ["parity"], integ=[1])
    r = explain_infeasible_mip(m)
    assert r["minimal_families"] == ["parity"], r


def test_feasible_problem_is_not_labelled():
    m = _mip([[1, 1], [1, 0]], "LG", [10, 2], ["capacity", "demand"])
    r = explain_infeasible_mip(m)
    assert r["minimal_families"] is None
    assert any("not proven infeasible" in n for n in r["notes"])


def test_amounts_are_in_row_units_not_mixed_across_families():
    r = explain_infeasible_mip(_mip([[1], [1]], "LG", [10, 14], ["minutes", "units"]))
    assert "row's own units" in r["slack_weights"]


def test_ratio_uses_rhs_and_floor_is_explicit():
    # capacity 10 vs demand 14 -> slack 4 total, ratios relative to each rhs
    m = _mip([[1], [1]], "LG", [10, 14], ["capacity", "demand"])
    r = explain_infeasible_mip(m)
    rows = {x["family"]: x for x in r["slack_rows"]}
    tot = sum(x["amount"] for x in r["slack_rows"])
    assert abs(tot - 4.0) < 1e-6
    for x in r["slack_rows"]:
        assert x["ratio_basis"] == "rhs"
        d = {"capacity": 10, "demand": 14}[x["family"]]
        assert abs(x["ratio"] - x["amount"] / d) < 1e-9


def test_zero_rhs_row_uses_floor_denominator():
    # x <= 0 and x >= 5: rhs 0 row has denominator floor 1 -> ratio == amount
    r = explain_infeasible_mip(_mip([[1], [1]], "LG", [0, 5], ["cap0", "dem"]),
                               normalize=False)
    for x in r["slack_rows"]:
        if x["family"] == "cap0":
            assert x["ratio_basis"] == "floor" and x["ratio"] == x["amount"]
        if x["family"] == "dem":
            assert x["ratio_basis"] == "rhs"
    assert "worst_ratio_by_family" in r


def test_normalize_minimizes_the_ratio_not_the_amount():
    # x <= 1000 (big rhs), x >= 1010; also y <= 1 , y >= 3 : two conflicts.
    # a single x with row weights: ratio weighting prefers relaxing the big-rhs row
    m = _mip([[1], [1]], "LG", [1000, 1010], ["a", "b"])
    r = explain_infeasible_mip(m, normalize=True)
    assert "ratio" in r["slack_weights"]
    assert abs(sum(x["amount"] for x in r["slack_rows"]) - 10.0) < 1e-6


def test_bucket_mip_rows_are_all_labelled_and_hard_demand_names_capacity():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
    from brain_core.synthetic import FnbParams, generate_fnb_factory
    from brain_core.rolling.two_level import build_bucket_mip
    import dataclasses
    p = generate_fnb_factory(FnbParams(
        seed=1, n_lines=3, n_skus=3, days=3, active_fraction=1.0,
        utilization=0.6, n_raw_materials=3, families=("DAIRY", "BAKERY")))
    mip, maps = build_bucket_mip(p.factory, p.params.horizon_start, 3,
                                 p.day_capacity_minutes * 0.3, 0.15)  # 30% of the capacity
    assert "unlabelled" not in set(mip.row_family)
    assert len(mip.row_family) == mip.A.shape[0]
    # the shipped bucket MIP is elastic (late variables): it stays feasible
    assert _milp_feasible(mip, np.ones(mip.A.shape[0], bool), 30.0) is True
    # a HARD version (late variables forced to 0) is infeasible with 30% of the capacity
    ub = mip.ub.copy()
    lo_cols = set(np.nonzero(np.asarray(mip.A.todense())[
        [i for i, f in enumerate(mip.row_family) if f.startswith("demand coverage")]
    ].any(axis=0))[0]) - set(maps["x"].values())
    # late variables = coverage-row columns that are not production columns
    lo_cols = [j for j in lo_cols if mip.integrality[j] == 0]
    for j in lo_cols:
        ub[j] = 0.0
    hard = dataclasses.replace(mip, ub=ub)
    r = explain_infeasible_mip(hard, time_limit_s=30.0)
    # measured: the capacity rows are NOT in the minimal set. The linking big-M
    # (sum x <= M y, M tight from capacity) already encodes the per-sku-day
    # capacity, so demand coverage conflicts with the linking family.
    assert r["minimal_families"] == ["demand coverage (late var)", "setup linking"], r
    assert r["slack_by_family"]["demand coverage (late var)"] > 0
    assert all(x["ratio"] > 0 for x in r["slack_rows"])
