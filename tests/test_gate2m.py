"""Gate-2M harness units: sharding, per-plant record, revalidation."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "benchmarks" / "gate2m"))

from common import plant_params, revalidate_plant, run_plant, shard_indices
from brain_core.synthetic import FnbParams


def test_shard_indices_cover_without_overlap():
    idx = [i for k in range(12) for i in shard_indices(k, 12, 96)]
    assert idx == list(range(96))
    idx = [i for k in range(5) for i in shard_indices(k, 5, 7)]
    assert idx == list(range(7))


def test_run_plant_and_revalidate_tiny():
    params = FnbParams(seed=7, n_lines=3, n_skus=40, days=4,
                       active_fraction=0.9, utilization=0.5,
                       n_raw_materials=5,
                       families=("DAIRY", "BAKERY", "SAUCE"))
    rec = run_plant(0, window_days=4, freeze_days=2, n_windows=2,
                    bucket_time_s=10, seq_time_s=5, params=params)
    assert rec["problems"] == [], rec["problems"][:3]
    assert all(w["vars"] > 0 and w["rows"] > 0 for w in rec["windows"])
    problems, kpis = revalidate_plant(rec, params=params)
    assert problems == [], problems[:3]
    assert kpis["assignments"] == len(rec["assignments"])


def test_revalidate_detects_a_broken_assignment():
    params = FnbParams(seed=7, n_lines=3, n_skus=40, days=4,
                       active_fraction=0.9, utilization=0.5,
                       n_raw_materials=5,
                       families=("DAIRY", "BAKERY", "SAUCE"))
    rec = run_plant(0, window_days=4, freeze_days=2, n_windows=1,
                    bucket_time_s=10, seq_time_s=5, params=params)
    assert rec["assignments"]
    rec["assignments"][0]["qty"] *= 100.0  # break line capacity
    problems, _ = revalidate_plant(rec, params=params)
    assert problems
