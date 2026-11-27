"""The progress guard is ON by default in the CG path and the long
runners; N is the documented, measured value."""
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "brain-core"))

from brain_core.guards.progress import DEFAULT_CG_PROGRESS_WINDOW  # noqa: E402
from brain_core.rolling.coupled_dw import column_generation  # noqa: E402


def test_default_window_is_on_and_above_measured_flat_stretches():
    sig = inspect.signature(column_generation)
    assert sig.parameters["progress_window"].default == \
        DEFAULT_CG_PROGRESS_WINDOW
    # measured longest natural flat stretch of the master objective at
    # the guard's own tolerance: 33 (3 x = 99); at the loosest: 77
    assert DEFAULT_CG_PROGRESS_WINDOW >= 100 > 3 * 33 - 1
    assert DEFAULT_CG_PROGRESS_WINDOW > 77


def _off_calls(path):
    bad = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        code = line.split("#", 1)[0]
        if re.search(r"progress_window\s*=\s*(None|0)\b", code):
            bad.append(f"{path}:{n}")
    return bad


def test_no_runner_switches_the_guard_off():
    bad = []
    for d in ("benchmarks", "serving", "packages"):
        for f in (ROOT / d).rglob("*.py"):
            bad += _off_calls(f)
    assert bad == [], bad
