import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from push_result import PushFailed, push_files  # noqa: E402


def _bare(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "res",
                    str(bare)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)],
                   check=True, capture_output=True)
    for c in (["checkout", "-q", "-b", "res"],
              ["-c", "user.name=a", "-c", "user.email=a@b", "commit",
               "-q", "--allow-empty", "-m", "init"],
              ["push", "-q", "origin", "res"]):
        subprocess.run(["git", *c], cwd=seed, check=True,
                       capture_output=True)
    return str(bare)


def test_push_lands_on_remote_and_nochange(tmp_path):
    bare = _bare(tmp_path)
    f = tmp_path / "r.json"
    f.write_text("{}")
    r = push_files([str(f)], bare, "res", "out", str(tmp_path / "w"))
    assert r["status"] == "pushed"
    chk = tmp_path / "chk"
    subprocess.run(["git", "clone", "-q", "-b", "res", bare, str(chk)],
                   check=True, capture_output=True)
    assert (chk / "out" / "r.json").read_text() == "{}"
    assert push_files([str(f)], bare, "res", "out",
                      str(tmp_path / "w"))["status"] == "nochange"


def test_fault_injection_missing_file_and_bad_remote(tmp_path):
    with pytest.raises(PushFailed):
        push_files([str(tmp_path / "nope.json")], "x", "res", "o",
                   str(tmp_path / "w"))
    f = tmp_path / "r.json"
    f.write_text("{}")
    with pytest.raises(PushFailed):
        push_files([str(f)], str(tmp_path / "does-not-exist.git"),
                   "res", "o", str(tmp_path / "w2"))


def _guarded(tmp_path, bare, cmd, timeout=30, stall=None):
    out = tmp_path / "res" / "x.json"
    argv = [sys.executable, str(ROOT / "benchmarks" / "run_guarded.py"),
            "--name", "t", "--timeout", str(timeout), "--out", str(out),
            "--push-remote", bare, "--push-branch", "res",
            "--push-dir", "d", "--push-workdir", str(tmp_path / "pw")]
    if stall:
        argv += ["--stall-s", str(stall)]
    r = subprocess.run(argv + ["--"] + cmd, capture_output=True,
                       text=True)
    return r, out


def _pushed_names(tmp_path, bare):
    chk = tmp_path / "chk2"
    subprocess.run(["git", "clone", "-q", "-b", "res", bare, str(chk)],
                   check=True, capture_output=True)
    return {p.name for p in (chk / "d").glob("*")}


GOOD = {"solves": {"s": {"status": "Optimal", "incumbent": 1.0,
                         "mip_gap": 0.0, "nodes": 3,
                         "int_violation": 0.0}}}


def test_guarded_ok_pushes_result_guard_and_log(tmp_path):
    bare = _bare(tmp_path)
    out = tmp_path / "res" / "x.json"
    cmd = [sys.executable, "-c",
           f"import json;json.dump({GOOD!r}, open({str(out)!r},'w'))"]
    (tmp_path / "res").mkdir()
    r, _ = _guarded(tmp_path, bare, cmd)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _pushed_names(tmp_path, bare) == {"x.json", "x.json.guard.json",
                                             "x.json.log"}


def test_fault_injection_hang_is_timeout_and_still_pushed(tmp_path):
    bare = _bare(tmp_path)
    (tmp_path / "res").mkdir()
    r, _ = _guarded(tmp_path, bare, [sys.executable, "-c",
                                     "import time;time.sleep(600)"],
                    timeout=3)
    assert r.returncode == 2
    assert "x.json.guard.json" in _pushed_names(tmp_path, bare)


def test_fault_injection_silent_stall_detected(tmp_path):
    bare = _bare(tmp_path)
    (tmp_path / "res").mkdir()
    r, _ = _guarded(tmp_path, bare, [sys.executable, "-c",
                                     "import time;time.sleep(600)"],
                    timeout=60, stall=3)
    assert r.returncode == 2 and "stalled" in r.stdout


def test_fault_injection_crash_and_invalid_mip_flagged(tmp_path):
    bare = _bare(tmp_path)
    (tmp_path / "res").mkdir()
    r, _ = _guarded(tmp_path, bare, [sys.executable, "-c",
                                     "raise SystemExit(7)"])
    assert r.returncode == 3
    bad = {"solves": {"s": dict(GOOD["solves"]["s"], nodes=-1)}}
    out = tmp_path / "res" / "x.json"
    cmd = [sys.executable, "-c",
           f"import json;json.dump({bad!r}, open({str(out)!r},'w'))"]
    r, _ = _guarded(tmp_path, bare, cmd)
    assert r.returncode == 4 and "invalid_not_a_mip" in r.stdout
