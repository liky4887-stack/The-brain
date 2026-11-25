"""Linear checkpoint pipeline + bounded repair loop.

run_pipeline executes the checkpoints IN ORDER over a claim and
returns a verdict: VERIFIED only when every check PASSes. BLOCKED is
reported as BLOCKED, never converted. The repair loop (verify_loop)
re-runs the WHOLE pipeline after each repair - never just the failed
check - for at most max_rounds repairs, then reports NOT VERIFIED.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from . import checks as C
from .claim import Claim

ORDER = [("remote-state", C.check_remote_state),
         ("clean-room-suite", C.check_clean_room_suite),
         ("artifacts-exist", C.check_artifacts_exist),
         ("numbers-recomputed", C.check_numbers_recomputed),
         ("labels-present", C.check_labels_present),
         ("no-placeholder", C.check_no_placeholder)]


@dataclass
class Verdict:
    verdict: str                      # VERIFIED / NOT VERIFIED / BLOCKED
    checks: dict[str, dict]
    repair_rounds: int = 0
    wall_s: float = 0.0
    notes: list[str] = field(default_factory=list)


def run_pipeline(claim: Claim, repo: str, runner=C.run,
                 suite_cmd=None) -> tuple[str, dict]:
    results: dict[str, dict] = {}
    overall = "VERIFIED"
    for name, fn in ORDER:
        kw = {}
        if name == "clean-room-suite" and suite_cmd is not None:
            kw["suite_cmd"] = suite_cmd
        if name in ("labels-present", "no-placeholder"):
            status, ev = fn(claim, repo)
        else:
            status, ev = fn(claim, repo, runner=runner, **kw)
        results[name] = {"status": status, "evidence": ev}
        if status == C.FAIL:
            overall = "NOT VERIFIED"
        elif status == C.BLOCKED and overall == "VERIFIED":
            overall = "BLOCKED"
    return overall, results


def verify_loop(claim: Claim, repo: str, repair,
                max_rounds: int = 2, runner=C.run,
                suite_cmd=None) -> Verdict:
    """repair(round_index, failures) is the claimant's fix hook; it must
    return a (possibly updated) claim. The whole pipeline re-runs after
    every repair. After max_rounds: NOT VERIFIED, honestly."""
    t0 = time.monotonic()
    failures: dict = {}
    rounds = 0
    while True:
        verdict, results = run_pipeline(claim, repo, runner=runner,
                                        suite_cmd=suite_cmd)
        if verdict == "VERIFIED":
            return Verdict(verdict, results, rounds,
                           round(time.monotonic() - t0, 1))
        if rounds >= max_rounds:
            return Verdict(verdict, results, rounds,
                           round(time.monotonic() - t0, 1),
                           ["repair budget exhausted; NOT marking done"])
        failures = {k: v for k, v in results.items()
                    if v["status"] != C.PASS}
        claim = repair(rounds, failures)
        rounds += 1


def main(argv: list[str]) -> int:
    claim = Claim.from_json(argv[1])
    repo = argv[2] if len(argv) > 2 else "."
    verdict, results = run_pipeline(claim, repo)
    out = {"verdict": verdict, "checks": results}
    print(json.dumps(out, indent=1))
    return 0 if verdict == "VERIFIED" else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv))
