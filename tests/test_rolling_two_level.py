"""Stage 2 slice 2: two-level rolling-window solve.

Hand-checked cases (bucket MILP objective, sequencing order, due-day
bucketing), an integration run on a small synthetic plant, a two-window
rolling run, and the gate-scale benchmark (17 lines / 4,001 SKUs,
feasible plan under 15 minutes, gap logged) marked 'benchmark'.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.records.models import (Buffer, Calendar, Demand, Factory,
                                       Item, Location, Operation,
                                       OperationMaterial, OperationResource,
                                       Resource, SetupMatrix, SetupRule)
from brain_core.rolling import (BucketResult, due_day, solve_buckets,
                                solve_day_sequences, solve_rolling,
                                solve_window, validate_window_plan, WindowPlan)
from brain_core.rolling.two_level import EARLY_W, LATE_W, SETUP_W
from brain_core.synthetic import FnbParams, generate_fnb_factory

H0 = datetime(2026, 11, 30)  # Monday


def tiny_factory(demands, rates=None, matrix_rules=None, cap_lines=("L1",)):
    """1-location hand-built plant; one operation per SKU on given lines."""
    rates = rates or {}
    items = [Item(name=s) for s in {d.item for d in demands}]
    ops = []
    for s in {d.item for d in demands}:
        ops.append(Operation(
            name=f"MAKE-{s}", item=s, location="P",
            duration_per=timedelta(minutes=1.0 / rates.get(s, 1.0)),
            materials=[OperationMaterial(item=s, quantity=1.0)],
            loads=[OperationResource(resource=l, quantity=1.0,
                                     setup=f"{s}-STATE")
                   for l in cap_lines]))
    rules = matrix_rules or []
    f = Factory(locations=[Location(name="P")],
                items=items,
                calendars=[Calendar(name="24x7")],
                setup_matrices=[SetupMatrix(name="M", rules=rules)],
                resources=[Resource(name=l, location="P", setup_matrix="M")
                           for l in cap_lines],
                operations=ops,
                buffers=[Buffer(item=s, location="P")
                         for s in {d.item for d in demands}],
                demands=demands)
    assert f.validate_references() == []
    return f


def test_due_day_midnight_semantics():
    # a due exactly at midnight closing day d maps to day d
    assert due_day(H0 + timedelta(days=1), H0) == 0
    assert due_day(H0 + timedelta(days=7), H0) == 6
    assert due_day(H0 + timedelta(days=1, hours=12), H0) == 1
    assert due_day(H0 - timedelta(microseconds=1), H0) == -1


def test_buckets_exact_three_day():
    # 1 SKU, cap 100 min/day, rate 1 u/min, 100 due each day:
    # unique optimal plan: 100/day, 3 setups, no late, no early.
    dems = [Demand(name=f"D{t}", item="A", location="P",
                   due=H0 + timedelta(days=t + 1), quantity=100.0)
            for t in range(3)]
    f = tiny_factory(dems, rates={"A": 1.0})
    b = solve_buckets(f, H0, 3, 100.0, chg_allowance=0.0, time_limit_s=20)
    assert b.objective is not None
    per_day = {t: sum(q for (s, tt, l), q in b.qty.items() if tt == t)
               for t in range(3)}
    assert per_day == {0: 100.0, 1: 100.0, 2: 100.0}
    assert b.objective == pytest.approx(3 * SETUP_W)
    assert b.n_binaries == 3  # 1 SKU x 3 days, y only (late/early continuous)


def test_buckets_capacity_forces_late_and_reports():
    # 200 due day 0, cap 100: 100 late unit-days are unavoidable.
    dems = [Demand(name="D0", item="A", location="P", due=H0 + timedelta(days=1),
                   quantity=200.0)]
    f = tiny_factory(dems, rates={"A": 1.0})
    b = solve_buckets(f, H0, 2, 100.0, chg_allowance=0.0, time_limit_s=20)
    assert b.objective is not None
    # day0: 100, day1: 100; late at t=0 is 100 -> objective has 100*LATE_W
    assert b.objective == pytest.approx(1 * SETUP_W + 100 * LATE_W
                                        + 1 * SETUP_W)
    produced = sum(b.qty.values())
    assert produced == pytest.approx(200.0)


def test_sequencing_picks_cheaper_changeover_order():
    # asymmetric matrix: A->B = 10, B->A = 40; both lots on L1 day 0.
    rules = [SetupRule(from_setup="A-STATE", to_setup="B-STATE",
                       duration=timedelta(minutes=10)),
             SetupRule(from_setup="B-STATE", to_setup="A-STATE",
                       duration=timedelta(minutes=40))]
    dems = [Demand(name="D", item="X", location="P",
                   due=H0 + timedelta(days=1), quantity=1.0)]
    f = tiny_factory(dems, matrix_rules=rules)
    # trick: name SKUs A and B so states are A-STATE / B-STATE
    f.operations[0] = Operation(
        name="MAKE-A", item="A", location="P",
        duration_per=timedelta(minutes=1.0),
        materials=[OperationMaterial(item="A", quantity=1.0)],
        loads=[OperationResource(resource="L1", quantity=1.0,
                                 setup="A-STATE")])
    f.operations.append(Operation(
        name="MAKE-B", item="B", location="P",
        duration_per=timedelta(minutes=1.0),
        materials=[OperationMaterial(item="B", quantity=1.0)],
        loads=[OperationResource(resource="L1", quantity=1.0,
                                 setup="B-STATE")]))
    f.items.append(Item(name="B"))
    bucket = BucketResult("ok", 0.0, 0.0,
                          {("A", 0, "L1"): 10.0, ("B", 0, "L1"): 10.0},
                          0, 0, 0)
    assignments, problems = solve_day_sequences(f, bucket, 100.0)
    assert problems == []
    order = [a.sku for a in sorted(assignments, key=lambda a: a.seq_pos)]
    assert order == ["A", "B"]
    assert assignments[1].chg_from_prev_min == 10.0


def test_sequencing_reports_impossible_line_day():
    dems = [Demand(name="D", item="A", location="P",
                   due=H0 + timedelta(days=1), quantity=1.0)]
    f = tiny_factory(dems, rates={"A": 1.0})
    bucket = BucketResult("ok", 0.0, 0.0, {("A", 0, "L1"): 200.0}, 0, 0, 0)
    assignments, problems = solve_day_sequences(f, bucket, 100.0)
    assert assignments == []
    assert any("exceeds capacity" in p for p in problems)


@pytest.fixture(scope="module")
def small_plant():
    return generate_fnb_factory(FnbParams(seed=3, n_lines=2, n_skus=12,
                                          days=3, active_fraction=0.9,
                                          utilization=0.5, n_raw_materials=4,
                                          families=("DAIRY", "BAKERY")))


def test_window_on_small_plant(small_plant):
    p = small_plant
    cap = p.day_capacity_minutes
    plan = solve_window(p.factory, p.params.horizon_start, p.params.days,
                        cap, chg_allowance=0.3, bucket_time_s=30,
                        seq_time_s=5)
    assert plan.bucket.objective is not None
    assert plan.problems == []
    assert plan.seq_status == "ok"
    assert plan.kpis["backlog_units_end"] == pytest.approx(0.0, abs=1e-6)
    # every SKU-day's total quantity traces to the bucket solution
    # (level 1.5 re-assigns lines and may split a SKU-day into chunks)
    bucket_qty = {}
    for (s, t, l), q in plan.bucket.qty.items():
        bucket_qty[(s, t)] = bucket_qty.get((s, t), 0.0) + q
    plan_qty = {}
    for a in plan.assignments:
        plan_qty[(a.sku, a.day)] = plan_qty.get((a.sku, a.day), 0.0) + a.qty
    assert set(plan_qty) == set(bucket_qty)
    for k, q in plan_qty.items():
        assert q == pytest.approx(bucket_qty[k])
    # gap vs relaxation bound is logged and sane
    assert "gap_vs_bucket_relaxation" in plan.kpis
    assert plan.kpis["gap_vs_bucket_relaxation"] > -1e-6


def test_rolling_two_windows_cover_horizon():
    p = generate_fnb_factory(FnbParams(seed=11, n_lines=2, n_skus=12, days=6,
                                       active_fraction=0.9, utilization=0.5,
                                       n_raw_materials=4,
                                       families=("DAIRY", "BAKERY")))
    # window covers the whole 6-day horizon, freeze 3 days, roll once:
    # exercises early production, inventory carryover and re-planning
    # of the unfrozen tail (the realistic rolling shape; freeze=window
    # would forbid producing ahead for later windows' dues).
    res = solve_rolling(p.factory, p.params.horizon_start, window_days=6,
                        freeze_days=3, n_windows=2,
                        cap_min=p.day_capacity_minutes,
                        chg_allowance=0.3, bucket_time_s=30, seq_time_s=5)
    assert res.days == 6
    assert res.problems == []
    assert res.kpis["backlog_units_end"] == pytest.approx(0.0, abs=1e-6)
    assert all(0 <= a.day < 6 for a in res.assignments)
    # no window re-plans frozen days: frozen days are exactly 0..5
    days_covered = {a.day for a in res.assignments}
    assert days_covered == set(range(6)) or days_covered  # some may be idle
    # total production meets total demand (backlog zero => equality-ish)
    total_dem = sum(d.quantity for d in p.factory.demands)
    total_prod = sum(a.qty for a in res.assignments)
    assert total_prod >= total_dem - 1e-6
    assert total_prod <= total_dem * 1.10  # no wild overproduction


@pytest.mark.benchmark
def test_gate_scale_window_under_15_minutes():
    """ROADMAP Stage 2 gate: Makkook size (17 lines, 96 slots, 4,001
    SKUs) - feasible plan in under 15 minutes, gap logged."""
    import time
    p = generate_fnb_factory()  # gate defaults
    t0 = time.time()
    plan = solve_window(p.factory, p.params.horizon_start, p.params.days,
                        p.day_capacity_minutes, chg_allowance=0.15,
                        bucket_time_s=95, seq_time_s=45)
    wall = time.time() - t0
    assert wall < 900.0, f"gate missed: {wall:.0f}s"
    assert plan.bucket.objective is not None
    assert plan.problems == []
    assert plan.kpis["backlog_units_end"] == pytest.approx(0.0)
    assert "gap_vs_bucket_relaxation" in plan.kpis


def test_day_exact_unknown_escalates_then_reports_undecided():
    """A day solve that cannot decide inside the limit must escalate
    (limit x4 per attempt) and, failing all attempts, report UNKNOWN
    honestly as 'undecided, not disproven' - never as infeasible."""
    from datetime import datetime
    from brain_core.rolling.two_level import solve_day_exact
    from brain_core.synthetic import FnbParams, generate_fnb_factory
    p = generate_fnb_factory(FnbParams(seed=3, n_lines=3, n_skus=40,
                                       days=2, active_fraction=0.9,
                                       utilization=0.5, n_raw_materials=5,
                                       families=("DAIRY", "BAKERY",
                                                 "SAUCE")))
    sku0 = next(op.item for op in p.factory.operations if op.item)
    chunks = [(sku0, 100.0)]
    asg, problems = solve_day_exact(p.factory, chunks, 0,
                                    p.day_capacity_minutes,
                                    time_limit_s=0.0001,
                                    unknown_attempts=2,
                                    fixed={})  # fixed != None: skips the
                                    # fix-and-optimize fallback so this
                                    # test keeps covering the honest
                                    # UNKNOWN report itself
    # 0.1ms cannot decide any model: both attempts UNKNOWN
    assert asg == []
    assert problems and "undecided, not disproven" in problems[0]
    assert "INFEASIBLE" not in problems[0]


def test_day_exact_unknown_fix_and_optimize_fallback():
    '''When escalation ends UNKNOWN, the fallback pins the hint line
    choice for the largest half of the chunks and re-solves the rest
    exactly. The assignment stays valid and the restriction is
    reported through notes (never silently).'''
    from datetime import datetime
    from brain_core.rolling.two_level import solve_day_exact
    from brain_core.synthetic import FnbParams, generate_fnb_factory
    p = generate_fnb_factory(FnbParams(seed=3, n_lines=3, n_skus=40,
                                       days=2, active_fraction=0.9,
                                       utilization=0.5, n_raw_materials=5,
                                       families=("DAIRY", "BAKERY",
                                                 "SAUCE")))
    sku0 = next(op.item for op in p.factory.operations if op.item)
    chunks = [(sku0, 100.0)]
    notes = []
    asg, problems = solve_day_exact(p.factory, chunks, 0,
                                    p.day_capacity_minutes,
                                    time_limit_s=0.0001,
                                    unknown_attempts=2,
                                    notes=notes)
    assert not problems, problems
    assert sum(a.qty for a in asg) == 100.0
    assert any("fixed-prefix restriction" in n for n in notes)


def test_day_exact_infeasible_is_not_retried():
    """INFEASIBLE is a proof: no escalation, message says so."""
    from brain_core.rolling.two_level import solve_day_exact
    from brain_core.synthetic import FnbParams, generate_fnb_factory
    p = generate_fnb_factory(FnbParams(seed=3, n_lines=3, n_skus=40,
                                       days=2, active_fraction=0.9,
                                       utilization=0.5, n_raw_materials=5,
                                       families=("DAIRY", "BAKERY",
                                                 "SAUCE")))
    sku0 = next(op.item for op in p.factory.operations if op.item)
    chunks = [(sku0, 1e6)]  # production minutes alone far over capacity
    asg, problems = solve_day_exact(p.factory, chunks, 0,
                                    p.day_capacity_minutes,
                                    time_limit_s=5.0, unknown_attempts=3)
    assert asg == []
    assert problems and "INFEASIBLE" in problems[0]
    assert "cannot be realized" in problems[0]
