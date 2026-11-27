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
