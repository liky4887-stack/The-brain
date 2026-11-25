"""Stage 3, slice 6: the four-week shadow pilot gate.

Small-instance gate runs in the suite; the medium-scale four-week
evidence run is benchmark-marked.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.audit import AuditLog
from brain_core.shadow import run_shadow_pilot
from brain_core.synthetic import FnbParams

SMALL = FnbParams(seed=0, n_lines=3, n_skus=40, days=4,
                  active_fraction=0.9, utilization=0.5,
                  n_raw_materials=5,
                  families=("DAIRY", "BAKERY", "SAUCE"))


def test_shadow_pilot_four_weeks_both_plans_scored(tmp_path):
    audit = tmp_path / "shadow.jsonl"
    res = run_shadow_pilot(weeks=4, cap_min=96 * 15, params=SMALL,
                           bucket_time_s=20, seq_time_s=5,
                           week0_seed=42, audit_path=audit)
    assert res.all_plans_valid, [
        (r.week, r.optimizer_problems[:2], r.naive_problems[:2])
        for r in res.weeks]
    # both plans scored by the same validator, no worse on either
    # dimension, strictly better on at least one (measured EPS rule)
    assert res.total_optimizer_changeover_min <= \
        res.total_naive_changeover_min + 1e-6
    assert res.total_optimizer_late_units <= \
        res.total_naive_late_units + 1e-6
    assert res.beats_naive
    # audit: 4 weeks x 2 plans, distinct digests, measured latency
    assert res.audit_entries == 8
    entries = AuditLog(audit).entries()
    digests = {e["digest"] for e in entries}
    assert len(digests) == 8        # 8 distinct plans recorded
    for e in entries:
        assert e["kind"] == "shadow_week"
        assert e["decision_latency_s"] >= 0.0
        assert "changeover_minutes" in e["kpis"]
        assert "backlog_units_end" in e["kpis"]
    per_week = {}
    for e in entries:
        per_week.setdefault(e["detail"]["week"], set()).add(
            e["detail"]["side"])
    assert per_week == {w: {"optimizer", "naive"} for w in range(4)}


@pytest.mark.benchmark
def test_shadow_pilot_gate_medium_scale():
    """The Stage 3 gate evidence: 4 weeks at 6 lines x 400 SKUs."""
    params = FnbParams(n_lines=6, n_skus=400, days=7,
                       active_fraction=0.25, utilization=0.65,
                       n_raw_materials=30)
    res = run_shadow_pilot(weeks=4, cap_min=96 * 15, params=params,
                           bucket_time_s=60, seq_time_s=20,
                           week0_seed=1000,
                           audit_path="/tmp/shadow4-audit.jsonl")
    assert res.all_plans_valid, [
        (r.week, r.optimizer_problems[:2]) for r in res.weeks]
    assert res.beats_naive
    print(f"shadow gate: opt chg {res.total_optimizer_changeover_min:.0f} "
          f"vs naive {res.total_naive_changeover_min:.0f} min; "
          f"opt late {res.total_optimizer_late_units:.0f} vs "
          f"naive {res.total_naive_late_units:.0f} units")
