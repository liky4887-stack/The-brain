"""Freeze expected plant data hashes into a committed manifest.

Review-#9 point 6: hash checks must compare against a FROZEN manifest
generated once at a recorded SHA and committed - never against the
code under test, or the check is circular (a generator bug would forge
its own expectation). This script is that freeze. Regenerate ONLY as a
deliberate, reviewed act (the generator changed on purpose); the diff
on plants-manifest.json is the audit trail, and any ladder block whose
recorded hashes no longer match the new manifest is stale and must be
re-run.

Usage: python benchmarks/scale/generate_manifest.py [--count 8192]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gate2m"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "packages", "brain-core"))

from common import plant_data_hash  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "plants-manifest.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=8192,
                    help="plants 0..count-1 (blocks A-D at 2048 each)")
    a = ap.parse_args()
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True, check=True).stdout.strip()
    manifest = {
        "kind": "plants-manifest",
        "generated_at_sha": sha,
        "generator": "benchmarks/gate2m/common.py::plant_params "
                     "(FnbParams(seed=BASE_SEED + i, days=14))",
        "count": a.count,
        "hashes": {str(i): plant_data_hash(i) for i in range(a.count)},
    }
    with open(OUT, "w") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    print(f"wrote {OUT}: {a.count} plants at {sha}")


if __name__ == "__main__":
    main()
