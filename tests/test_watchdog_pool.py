"""Watchdog, pool isolation and stall tests (from the user's local
hardening patch, split out; each failed or could not run on main 2a9a39f
as noted in the PR)."""
import os
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "packages" / "brain-core"))
sys.path.insert(0, os.path.dirname(__file__))

import helpers_guard_steps as h  # noqa: E402
from brain_core.guards.watchdog import (heartbeat_age_s,  # noqa: E402
                                        run_pool, run_step)


# ---- watchdog: result transport and heartbeat -------------------------

def test_big_result_is_returned_not_reported_as_timeout():
    # old code: join(timeout) before q.get -> a 1 MB result could not
    # leave the pipe, the child could not exit, status 'timeout'
    r = run_step("big", h.big, (1_000_000,), timeout_s=30)
    assert r.status == "ok", (r.status, r.detail)
    assert len(r.value) == 1_000_000
    assert r.wall_s < 20


def test_dead_child_reported_fast_not_after_full_timeout():
    r = run_step("die", h.die, timeout_s=120)
    assert r.status == "killed" and r.wall_s < 30


def test_heartbeat_is_refreshed_while_step_runs(tmp_path):
    hb = str(tmp_path / "hb")
    t0 = time.time()
    r = run_step("slow", h.sleep_for, (2.5,), timeout_s=60,
                 heartbeat_path=hb, heartbeat_every_s=0.5)
    assert r.status == "ok"
    last_beat = float(open(hb).read())
    assert last_beat - t0 >= 1.5          # beat AFTER the first one
    assert heartbeat_age_s(hb) is not None
    assert heartbeat_age_s(str(tmp_path / "none")) is None


# ---- run_pool: failure isolation --------------------------------------

def test_pool_isolates_exception_and_keeps_other_results():
    out = run_pool(h.cell, [1, "boom", 3], max_workers=2)
    assert [r.status for r in out] == ["ok", "error", "ok"]
    assert out[0].value == 2 and out[2].value == 6
    assert "bad cell" in out[1].detail and "twice" in out[1].detail


def test_pool_dead_worker_innocent_jobs_recovered_on_retry():
    out = run_pool(h.cell, [1, "die", 3, 4], max_workers=2)
    assert out[1].status == "killed"         # died again, alone
    assert "BrokenProcessPool" in out[1].detail
    assert [out[i].value for i in (0, 2, 3)] == [2, 6, 8]


def test_pool_wall_budget_always_returns():
    t0 = time.monotonic()
    out = run_pool(h.cell, [1, "hang"], max_workers=2, wall_budget_s=5)
    assert time.monotonic() - t0 < 60
    assert out[0].status == "ok" and out[1].status == "timeout"


# ---- runtime invariants on real plans ---------------------------------

def _plan():
    from test_decompose import H0, _solvable_two_cell_factory
    from brain_core.rolling import solve_window
def test_decomposed_cell_failure_is_named_not_raised():
    from test_decompose import H0, _solvable_two_cell_factory
    from brain_core.decompose import solve_decomposed
    f = _solvable_two_cell_factory()
    # an unknown kwarg makes solve_window raise TypeError in every cell
    res = solve_decomposed(f, H0, days=2, cap_min=480.0,
                           bucket_time_s=5, seq_time_s=2,
                           not_a_solver_option=1)
    assert res.cells == 2
    assert any("cell 0 failed" in x for x in res.problems)
    assert any("cell 1 failed" in x for x in res.problems)
    assert "cell-failed" in res.plan.bucket.status


# ---- stall detector: slow step inside its timeout ---------------------

def test_stalled_step_killed_before_timeout():
    t0 = time.monotonic()
    r = run_step("stall", h.progress_then_stall, (3,), timeout_s=600,
                 stall_s=3)
    assert r.status == "stalled", (r.status, r.detail)
    assert time.monotonic() - t0 < 60


def test_moving_step_not_flagged_as_stalled():
    r = run_step("move", h.keeps_moving, (12,), timeout_s=120, stall_s=2)
    assert r.status == "ok" and r.value == 12


