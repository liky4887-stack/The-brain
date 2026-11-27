"""The per-test wall budget (tests/conftest.py): a slow test fails by name.
Fail-before: without the conftest a 0.3 s test under a 0.05 s budget passed."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONF = Path(__file__).resolve().parent / "conftest.py"

SRC = '''
import time
import pytest

def test_slow():
    time.sleep(0.3)

@pytest.mark.budget(5)
def test_slow_but_declared():
    time.sleep(0.3)
'''


def _run(tmp_path, env_budget):
    shutil.copy(CONF, tmp_path / "conftest.py")
    (tmp_path / "test_x.py").write_text(SRC)
    env = {k: v for k, v in os.environ.items()
           if k not in ("BRAIN_TEST_BUDGET_S", "PYTEST_XDIST_WORKER")}
    if env_budget:
        env["BRAIN_TEST_BUDGET_S"] = env_budget
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-p", "no:xdist", str(tmp_path)],
        capture_output=True, text=True, cwd=tmp_path, env=env, timeout=120)


def test_slow_test_fails_by_name_and_declared_budget_passes(tmp_path):
    r = _run(tmp_path, "0.05")
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "test_slow " in out or "test_x.py::test_slow" in out
    assert "over wall budget" in out
    assert "1 failed, 1 passed" in out, out


def test_budget_is_off_when_unset(tmp_path):
    r = _run(tmp_path, None)
    assert r.returncode == 0, r.stdout + r.stderr
