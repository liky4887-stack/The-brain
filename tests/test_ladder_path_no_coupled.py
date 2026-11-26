"""Measured proof: the ladder solve path never imports coupled code.

The coupled optimizer (brain_core.coupled*) is track 2 research code.
The ladder (benchmarks/gate2m) is track 1 throughput/reliability
measurement on independent plants. A bug in coupled code (e.g. the
integer_master UB overwrite fixed in 0d7b3e7) must be UNABLE to touch
ladder numbers. Claim is not asserted from reading imports: this test
runs the real ladder path (benchmarks/gate2m/common.run_plant, the
same entry the CI shard job uses) on a tiny plant while a meta-path
import hook turns any brain_core.coupled* import into a failure, then
asserts the coupled modules are absent from sys.modules afterwards.
Lazy/transitive imports are caught the same way.
"""

from __future__ import annotations

import importlib.abc
import os
import sys

import pytest

GATE2M = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "gate2m")
BRAIN_CORE = os.path.join(os.path.dirname(__file__), "..", "packages", "brain-core")


class _CoupledImportSentinel(importlib.abc.MetaPathFinder):
    """Any attempt to import brain_core.coupled* fails the test run."""

    def find_module(self, fullname, path=None):  # noqa: D102
        if fullname == "brain_core.coupled" or fullname.startswith(
            "brain_core.coupled."
        ) or ".coupled" in fullname:
            raise AssertionError(
                f"ladder path attempted to import coupled code: {fullname}"
            )
        return None


_CHILD = r"""
import importlib.abc, os, sys
GATE2M, BRAIN_CORE = sys.argv[1], sys.argv[2]
for p in (GATE2M, BRAIN_CORE):
    if p not in sys.path:
        sys.path.insert(0, p)


class Sentinel(importlib.abc.MetaPathFinder):
    def find_module(self, fullname, path=None):
        if fullname == "brain_core.coupled" or fullname.startswith(
                "brain_core.coupled.") or ".coupled" in fullname:
            raise AssertionError("ladder path attempted to import coupled "
                                 "code: " + fullname)
        return None


sys.meta_path.insert(0, Sentinel())
from common import BASE_SEED, run_plant
from brain_core.synthetic import FnbParams
rec = run_plant(0, params=FnbParams(seed=BASE_SEED, days=14), n_windows=1,
                bucket_time_s=15.0, seq_time_s=15.0)
assert rec["plant"] == 0
bad = [m for m in sys.modules
       if m.startswith("brain_core") and "coupled" in m]
assert not bad, "ladder path loaded coupled modules: %s" % bad
print("OK")
"""


@pytest.mark.timeout(180)
def test_ladder_path_never_imports_coupled():
    """Runs in a FRESH interpreter: in a full-suite run other test modules
    (test_coupled*.py) import the coupled code at collection time, so a
    sys.modules check inside the pytest process cannot tell what the
    ladder path itself loads (the in-process version failed in every
    full-suite run, found 2026-11-26)."""
    import subprocess
    r = subprocess.run(
        [sys.executable, "-c", _CHILD, os.path.abspath(GATE2M),
         os.path.abspath(BRAIN_CORE)],
        capture_output=True, text=True, timeout=170)
    assert r.returncode == 0 and "OK" in r.stdout, (r.stdout + r.stderr)[-2000:]
