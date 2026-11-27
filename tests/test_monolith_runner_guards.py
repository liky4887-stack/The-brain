"""Monolith runner: durable atomic writes, manifest in the record, caps
cache keyed on the class parameters for EVERY class (user's local patch,
split out). Smoke runs are ~3 s (n=1, easy)."""
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "packages" / "brain-core"))

from brain_core.guards.durable import write_run_json  # noqa: E402


def test_run_json_is_atomic_and_mirrored(tmp_path, monkeypatch):
    mirror = tmp_path / "mirror"
    monkeypatch.setenv("BRAIN_RUNS_DIR", str(mirror))
    target = Path("/tmp") / f"brain-test-{os.getpid()}.json"
    try:
        paths = write_run_json(target, {"obj": 1.5})
        assert json.loads(target.read_text()) == {"obj": 1.5}
        assert json.loads((mirror / target.name).read_text()) == \
            {"obj": 1.5}
        assert len(paths) == 2
        assert not list(Path("/tmp").glob(f".{target.name}.*.tmp"))
    finally:
        target.unlink(missing_ok=True)


def _run(tmp_path, tag, extra=None):
    out = tmp_path / f"ms-{tag}.json"
    env = {**os.environ, "MS_N": "1", "MS_CLASS": "easy", "MS_LIMIT": "20",
           "MS_CAP_SOLVE_S": "2", "MS_SOLVERS": "highspy:1",
           "MS_OUT": str(out), "BRAIN_RUNS_DIR": str(tmp_path / "runs"),
           "PYTHONPATH": str(_ROOT / "packages" / "brain-core"),
           **(extra or {})}
    r = subprocess.run([sys.executable,
                        str(_ROOT / "benchmarks" / "monolith_scaling.py")],
                       env=env, capture_output=True, text=True, timeout=150)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(out.read_text())


def test_smoke_record_carries_manifest_and_no_findings(tmp_path):
    rec = _run(tmp_path, "a")
    assert rec.get("manifest_hash") and rec.get("manifest")
    for s in rec["solves"].values():
        assert s["guard_findings"] == [], s["guard_findings"]
        assert s["manifest_hash"] == rec["manifest_hash"]


def test_caps_cache_is_keyed_on_class_params_for_easy(tmp_path):
    for p in glob.glob("/tmp/caps-easy-1-2*.json"):   # caches only
        os.unlink(p)
    _run(tmp_path, "b1")
    _run(tmp_path, "b2", {"MS_CLASS_JSON": json.dumps({"sup": 0.9})})
    files = glob.glob("/tmp/caps-easy-1-2*.json")
    tags = {p.rsplit("-p", 1)[-1] for p in files if "-p" in p[10:]}
    assert len(files) >= 2 and len(tags) >= 2, files
