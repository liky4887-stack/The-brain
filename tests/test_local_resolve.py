"""Stage 3, slice 1: event-triggered local re-solve.

Machine-down and rush-order on a frozen base plan: the plan stays
valid (same independent validator), untouched (line, day) lots do not
move, and the stability/wall metrics are honest. The gate-scale
benchmark (17 lines, <60s, <5% moved, within 2% of full re-solve) is
benchmark-marked.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.records.models import Demand
from brain_core.reschedule import machine_down, rush_order, stability
from brain_core.rolling import solve_window, validate_window_plan
from brain_core.rolling.two_level import WindowPlan, LotAssignment
from brain_core.synthetic import FnbParams, generate_fnb_factory

SMALL = FnbParams(seed=3, n_lines=3, n_skus=20, days=4,
                  active_fraction=0.9, utilization=0.4,
                  n_raw_materials=4,
                  families=("DAIRY", "BAKERY", "SAUCE"))


@pytest.fixture(scope="module")
def base():
    p = generate_fnb_factory(SMALL)
    plan = solve_window(p.factory, p.params.horizon_start, p.params.days,
                        p.day_capacity_minutes, bucket_time_s=20,
                        seq_time_s=5)
    assert plan.problems == []
    return p, plan


def test_machine_down_keeps_plan_valid_and_freezes_untouched(base):
    p, plan = base
    down_line = plan.assignments[0].line
    down_day = plan.assignments[0].day
    res = machine_down(p.factory, plan, down_line, down_day,
                       down_day + 1, p.day_capacity_minutes, seq_time_s=5)
    assert res.problems == [], res.problems[:3]
    # nothing runs on the downed line-day
    assert not [a for a in res.plan.assignments
                if a.line == down_line and a.day == down_day]
    # every untouched (line, day) keeps its base production exactly
    base_group = {}
    for a in plan.assignments:
        if a.day != down_day:
            base_group[(a.day, a.line, a.sku)] = \
                base_group.get((a.day, a.line, a.sku), 0.0) + a.qty
    new_group = {}
    for a in res.plan.assignments:
        new_group[(a.day, a.line, a.sku)] = \
            new_group.get((a.day, a.line, a.sku), 0.0) + a.qty
    for key, q in base_group.items():
        assert new_group.get(key, 0.0) == pytest.approx(q)
    # something had to move (the downed line-day's production)
    assert res.moved_units > 0
    assert res.moved_units >= res.displaced_units - 1e-6
    # 3 lines x 4 days: one line-day is ~1/12 of the plan
    assert res.moved_fraction < 0.5
    v_problems, kpis = validate_window_plan(p.factory, res.plan,
                                            p.day_capacity_minutes)
    assert v_problems == []


def test_rush_order_absorbed_with_base_intact(base):
    p, plan = base
    sku = plan.assignments[0].sku
    order = Demand(name="RUSH-1", item=sku, location=p.params.location,
                   due=p.params.horizon_start + timedelta(days=2),
                   quantity=50.0)
    res = rush_order(p.factory, plan, order, p.day_capacity_minutes,
                     seq_time_s=5)
    assert res.problems == [], res.problems[:3]
    produced = sum(a.qty for a in res.plan.assignments
                   if a.sku == sku and a.day <= 1)
    base_produced = sum(a.qty for a in plan.assignments
                        if a.sku == sku and a.day <= 1)
    assert produced >= base_produced + 50.0 - 1e-6
    assert res.moved_fraction < 0.5
    assert res.plan.kpis["backlog_units_end"] == pytest.approx(0.0)


def test_rush_order_unknown_item_raises(base):
    p, plan = base
    order = Demand(name="RUSH-X", item="NOPE",
                   due=p.params.horizon_start + timedelta(days=1),
                   quantity=10.0)
    with pytest.raises(ValueError, match="no operation"):
        rush_order(p.factory, plan, order, p.day_capacity_minutes)


def test_stability_counts_only_line_day_moves():
    mk = lambda line, day, sku, q: LotAssignment(line, day, sku, q, 0, 0.0)
    from datetime import datetime
    h0 = datetime(2026, 11, 30)
    b = WindowPlan(h0, 2, [mk("L1", 0, "A", 100), mk("L2", 0, "B", 50)],
                   None, "t")
    same = WindowPlan(h0, 2, [mk("L1", 0, "A", 100), mk("L2", 0, "B", 50)],
                      None, "t")
    moved, total, frac = stability(b, same)
    assert (moved, total, frac) == (0.0, 150.0, 0.0)
    resequenced = WindowPlan(h0, 2, [LotAssignment("L1", 0, "A", 100, 3,
                                                   30.0),
                                     mk("L2", 0, "B", 50)], None, "t")
    assert stability(b, resequenced)[0] == 0.0  # resequence != move
    shifted = WindowPlan(h0, 2, [mk("L2", 1, "A", 100),
                                 mk("L2", 0, "B", 50)], None, "t")
    moved, _, frac = stability(b, shifted)
    assert moved == 100.0 and frac == pytest.approx(100.0 / 150.0)


@pytest.mark.benchmark
def test_gate_machine_down_under_60s_within_2_percent():
    """Stage 3 gate: one line down for one day on the Makkook-scale
    plant - local re-solve under 60s, under 5% of units moved, proxy
    cost within 2% of a full overnight re-solve."""
    import time
    p = generate_fnb_factory()  # gate defaults
    cap = p.day_capacity_minutes
    t0 = time.time()
    base_plan = solve_window(p.factory, p.params.horizon_start,
                             p.params.days, cap, bucket_time_s=95,
                             seq_time_s=45)
    assert base_plan.problems == []
    down_line = sorted({a.line for a in base_plan.assignments})[0]
    res = machine_down(p.factory, base_plan, down_line, 2, 3, cap,
                       seq_time_s=45)
    assert res.wall_s < 60.0, f"local re-solve took {res.wall_s:.0f}s"
    assert res.moved_fraction < 0.05, \
        f"moved {res.moved_fraction:.1%} of units"
    # full overnight re-solve WITH the event honored (line capacity
    # zero on the down day) - the reference the gate compares against
    full = solve_window(p.factory, p.params.horizon_start,
                        p.params.days, cap, bucket_time_s=95,
                        seq_time_s=45,
                        cap_override={(down_line, 2): 0.0})
    assert time.time() - t0 < 900.0
    assert full.problems == []
    full_cost = full.kpis["proxy_cost"]
    local_cost = res.plan.kpis["proxy_cost"]
    assert local_cost <= full_cost * 1.02, \
        f"local {local_cost:.0f} vs full {full_cost:.0f}"
    assert res.problems == []
