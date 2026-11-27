"""Per-test wall budget: a test that gets slow fails BY NAME, long
before the 600 s hang timeout or the 30 min job limit.

BRAIN_TEST_BUDGET_S (unset = off, so local runs are unchanged) is the
default budget per test, call phase only. A test that is slow on
purpose declares its own: @pytest.mark.budget(400). Over budget ->
the session fails with the list. BRAIN_TEST_DURATIONS_OUT writes every
test's duration as JSON, for a trend across runs.
"""
import json
import os

import pytest

_DUR: dict[str, float] = {}
_OVER: list[tuple[str, float, float]] = []


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "budget(seconds): per-test wall budget override")


def _budget(item):
    m = item.get_closest_marker("budget")
    if m and m.args:
        return float(m.args[0])
    v = os.environ.get("BRAIN_TEST_BUDGET_S")
    return float(v) if v else None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if call.when != "call":
        return
    _DUR[item.nodeid] = round(call.duration, 3)
    b = _budget(item)
    if b is not None and call.duration > b and rep.passed:
        _OVER.append((item.nodeid, call.duration, b))
        rep.outcome = "failed"
        rep.longrepr = (f"over wall budget: {call.duration:.1f} s > "
                        f"{b:.0f} s (BRAIN_TEST_BUDGET_S or "
                        "@pytest.mark.budget)")


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("BRAIN_TEST_DURATIONS_OUT")
    if out and _DUR:
        worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
        path = out.replace(".json", f"-{worker}.json")
        with open(path, "w") as f:
            json.dump(_DUR, f, indent=1, sort_keys=True)
