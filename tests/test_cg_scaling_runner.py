"""coupled_cg_scaling runner: manifest-sealed, watchdogged, durable.
Fail-before: the old runner wrote one file at the very end, kept only the
last 3 problems, had no guard findings and no step timeout."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(tmp_path, **env_extra):
    out = tmp_path / "o.json"
    env = {**os.environ, "CG_SIZES": "2", "CG_OUT": str(out),
           "BRAIN_RUNS_DIR": str(tmp_path / "mirror"), **env_extra}
    r = subprocess.run([sys.executable, str(ROOT / "benchmarks"
                                            / "coupled_cg_scaling.py")],
                       capture_output=True, text=True, env=env, timeout=110)
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]
    return json.loads(out.read_text())


def test_row_is_stamped_complete_and_keeps_all_problems(tmp_path):
    d = _run(tmp_path)
    assert d["complete"] is True and d["manifest_hash"]
    row = d["rows"][0]
    assert row["manifest_hash"] == d["manifest_hash"]
    assert row["n_problems"] == len(row["problems"])
    assert row["guard_findings"] == []
    assert (tmp_path / "mirror").exists()       # mirrored off the run dir


def test_a_step_over_its_timeout_is_a_recorded_failure_not_a_crash(tmp_path):
    d = _run(tmp_path, CG_STEP_TIMEOUT_S="1")
    row = d["rows"][0]
    assert d["complete"] is True
    assert row["measured"] is False and row["status"] != "ok"
    assert row["guard_findings"][0][0] == "step_failed"


def test_default_primal_is_sound_on_size_2(tmp_path):
    """Fail-before: alloc_every=0 gave UB 118,373,179 vs LB 60,940,576 (proven
    gap 0.485) on size 2; with alloc_every=5 the gap was 8.7e-6 locally.
    Real size-2 run, so this is a measurement on one instance, not a general
    proof. The cause of the weak columns-only primal is a hypothesis."""
    row = _run(tmp_path)["rows"][0]
    assert row["alloc_every"] == 5 and row["primal_note"] == "ok"
    assert row["proven_gap"] < 0.01, row["proven_gap"]


def test_alloc_every_zero_row_is_labelled_primal_not_meaningful(tmp_path):
    row = _run(tmp_path, CG_ALLOC_EVERY="0")["rows"][0]
    assert row["primal_note"].startswith("primal not meaningful")
