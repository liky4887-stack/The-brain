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


@pytest.mark.timeout(180)
def test_ladder_path_never_imports_coupled():
    for p in (os.path.abspath(GATE2M), os.path.abspath(BRAIN_CORE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    sentinel = _CoupledImportSentinel()
    sys.meta_path.insert(0, sentinel)
    try:
        from common import BASE_SEED, run_plant  # the CI shard entry
        from brain_core.synthetic import FnbParams

        rec = run_plant(
            0,
            params=FnbParams(seed=BASE_SEED, days=14),
            n_windows=1,
            bucket_time_s=15.0,
            seq_time_s=15.0,
        )
        assert rec["plant"] == 0
    finally:
        sys.meta_path.remove(sentinel)
    loaded = [m for m in sys.modules if m.startswith("brain_core")]
    bad = [m for m in loaded if "coupled" in m]
    assert not bad, f"ladder path loaded coupled modules: {bad}"
