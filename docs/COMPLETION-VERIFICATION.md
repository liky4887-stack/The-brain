# Completion verification ("never a fake done")

Status: PLAN v1 + implementation (2026-11-25, owner voice note).

A stage, slice or gate is complete only when an INDEPENDENT pipeline
says so, over a machine-readable claim - never because an agent's
report says so. The harness lives in verify/ and is used by every
future stage/slice/gate close-out.

## Claim schema (verify/claim.json per close-out)

```
{ "title": "...", "sha": "<claimed merged commit>",
  "remote": "origin", "branch": "main",
  "tests": {"passed": N, "skipped": M},        # compared to a real run
  "artifacts": ["path-or-branch:file", ...],   # must exist, parse
  "recompute": {"cmd": "...", "expect": {"field": value}},  # rerun + compare
  "report_file": "path",                        # the human report text
  "deliverables": ["paths of claimed files"] }
```

## Linear checkpoints (each independent, each emits PASS/FAIL/BLOCKED + evidence)

1. remote-state: `git ls-remote` on the claimed branch equals the
   claimed SHA. Catches "merged" claims that never landed.
2. clean-room-suite: clone the claimed SHA into a fresh temp dir,
   fresh venv, install, run the suite; parsed counts must match the
   claim. NOTE (honest substitution): this environment has NO docker,
   so the clean room is a fresh clone + fresh venv, labelled as such;
   on the Actions fabric a job IS a clean VM (strongest variant, used
   by gate2m already).
3. artifacts-exist: every claimed artifact exists, is non-empty, and
   parses (JSON where applicable). Branch artifacts read via git show.
4. numbers-recomputed: the claim's recompute command is run; named
   numbers compared within tolerance. The claim's numbers never stand
   on the claimant's word.
5. labels-present: the report's quantitative claims carry
   MEASURED/EXTRAPOLATED labels; UNKNOWN is never reported as
   infeasible/impossible (wording scan).
6. no-placeholder: deliverable files scanned for TODO, FIXME,
   NotImplementedError, "placeholder", "dummy", "fake" markers.

## Repair loop (bounded, honest)

Any FAIL -> structured failure report -> the claimant repairs -> the
WHOLE pipeline re-runs (never only the failed check) -> max 2 repair
rounds -> final verdict VERIFIED or NOT VERIFIED with evidence.
BLOCKED (a check that cannot run, e.g. no network) is reported, not
converted into a pass. There is no "mark done" path that skips this.

## Non-goals / honest limits

- It verifies claims about THIS repo's state and artifacts; it cannot
  prove business outcomes.
- The clean-room venv shares the host kernel/network; it is not a
  security sandbox.
- Free only: stdlib + git + venv. No services, no tokens.
