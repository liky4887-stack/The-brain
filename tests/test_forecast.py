"""Stage 3, slice 3: Holt-Winters forecasts, ranges, safety stock.

The gate is measured, not asserted: rolling-origin MAE vs the
seasonal-naive baseline on synthetic history with trend + growing
seasonality. The forecaster is a model zoo (Holt-Winters grid +
naive baselines) selected per SKU by back-test error, so the gate is:
never meaningfully worse than seasonal-naive on any SKU, materially
better overall. A strict per-SPU win is statistically impossible at
this noise level (10%): on SKUs where neither model class has a real
edge, the 8-fold comparison is decided by luck, and the honest
requirement is bounded regret, not a guaranteed win.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.forecast import (apply_safety_stock, forecast,
                                 make_synthetic_history,
                                 rolling_origin_mae,
                                 seasonal_naive_forecast)
from brain_core.records.models import Buffer, Factory, Item, Location


def test_deterministic_seasonal_series_forecast_well():
    """No noise: the model should nearly nail the next point."""
    import math
    season = 13
    series = [100 * (1 + 0.003 * t)
              + 20 * math.sin(2 * math.pi * t / season)
              for t in range(104)]
    f = forecast(series, season)
    actual = 100 * (1 + 0.003 * 104) + 20 * math.sin(
        2 * math.pi * 104 / season)
    assert abs(f.mean - actual) / actual < 0.05
    assert f.lower <= f.mean <= f.upper


def test_gate_beats_seasonal_naive_on_synthetic_history():
    """Stage 3 gate: measured rolling-origin MAE vs seasonal-naive.

    Per SKU the zoo must never be meaningfully worse (<= 1.05x), and
    overall it must be materially better (>= 10% total MAE reduction).
    """
    histories = make_synthetic_history(sku_count=6, weeks=156,
                                       season=52, seed=7)
    zoo_total, sn_total = 0.0, 0.0
    for sku, h in histories.items():
        z_mae, sn_mae, cov = rolling_origin_mae(h, season=52,
                                                origins=8)
        zoo_total += z_mae
        sn_total += sn_mae
        print(f"{sku}: zoo MAE {z_mae:.1f} vs SN {sn_mae:.1f} "
              f"(coverage {cov:.2f})")
        assert z_mae <= 1.05 * sn_mae, (
            f"{sku}: zoo {z_mae:.1f} meaningfully worse than "
            f"seasonal-naive {sn_mae:.1f}")
    improvement = 1 - zoo_total / sn_total
    print(f"TOTAL: zoo {zoo_total:.1f} vs SN {sn_total:.1f} "
          f"({100 * improvement:.1f}% better)")
    assert improvement >= 0.10, (
        f"only {100 * improvement:.1f}% better than seasonal-naive")


def test_range_coverage_reported_and_sane():
    h = make_synthetic_history(sku_count=1, weeks=156, season=52,
                               seed=11)["SKU-0000"]
    _, _, cov = rolling_origin_mae(h, season=52, origins=8)
    # not a calibrated-probability claim: the range must just not be
    # absurdly narrow or wide on this structure
    assert cov >= 0.5


def test_safety_stock_feeds_buffer_minimum():
    f = Factory(locations=[Location(name="P")],
                items=[Item(name="A")],
                buffers=[Buffer(item="A", location="P", onhand=100.0,
                                minimum=10.0)])
    report = apply_safety_stock(f, {"A": 250.0, "GHOST": 50.0})
    assert f.buffers[0].minimum == 250.0
    assert report == {"touched": ["A"], "missing_buffer": ["GHOST"]}


def test_safety_stock_never_lowers_minimum():
    f = Factory(locations=[Location(name="P")],
                items=[Item(name="A")],
                buffers=[Buffer(item="A", location="P", onhand=100.0,
                                minimum=500.0)])
    apply_safety_stock(f, {"A": 100.0})
    assert f.buffers[0].minimum == 500.0
