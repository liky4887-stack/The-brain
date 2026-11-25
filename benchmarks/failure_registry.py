"""Known-failure registry: pause -> auto-heal -> resume, and later
blocks learn from earlier failures.

The registry (benchmarks/registry/known-failures.json, committed) maps
a failure SIGNATURE to its diagnosis, fix commit and status. The
orchestrator consults it before re-dispatching a failed ladder step:

- signature known + fixed: verify the run's SHA contains the fix,
  re-dispatch ONCE (bounded); if the fix commit is missing, pause and
  say so (a re-run without the fix just re-fails).
- signature known + open: pause; healing budget is not spent on a
  failure already being worked.
- signature new: diagnose + fix (branch, full suite, verification
  harness, merge with review visibility via parent report), record the
  entry, resume. At most MAX_HEAL_ATTEMPTS per (step, signature).

GitHub reality: runners cannot pause mid-matrix. "Pause" means the
orchestrator holds the next config push; "resume" means re-dispatch
(push). Within a block, failed shards keep their evidence (failure-
isolated records); nothing is cancelled.
"""
from __future__ import annotations

import hashlib
import json
import os

MAX_HEAL_ATTEMPTS = 2
REGISTRY_PATH = os.path.join("benchmarks", "registry",
                             "known-failures.json")


def signature(error_text: str) -> str:
    """Stable 12-char signature: error class + normalized message with
    volatile parts (digits, paths, hex) stripped, so the SAME failure
    is recognized across runs, runners and plant indices."""
    import re
    norm = re.sub(r"0x[0-9a-fA-F]+|[0-9]+", "#", error_text)
    norm = re.sub(r"/[^\s]+", "<path>", norm)
    return hashlib.sha256(norm.strip().encode()).hexdigest()[:12]


def load(repo: str) -> dict:
    path = os.path.join(repo, REGISTRY_PATH)
    if os.path.exists(path):
        return json.load(open(path))
    return {"version": 1, "entries": {}}


def save(repo: str, reg: dict) -> str:
    path = os.path.join(repo, REGISTRY_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(reg, open(path, "w"), indent=1)
    return path


def record(repo: str, sig: str, *, summary: str, run_id: str,
           sha: str, step: int, status: str = "open",
           fix_commit: str | None = None,
           avoidance: str = "") -> dict:
    """Insert or update an entry; returns it."""
    reg = load(repo)
    e = reg["entries"].get(sig, {"attempts": 0, "first_seen": {}})
    e.update({"signature": sig, "summary": summary[:300],
              "status": status, "fix_commit": fix_commit,
              "avoidance": avoidance,
              "last_seen": {"run_id": run_id, "sha": sha, "step": step}})
    if not e["first_seen"]:
        e["first_seen"] = {"run_id": run_id, "sha": sha, "step": step}
    reg["entries"][sig] = e
    save(repo, reg)
    return e


def healing_decision(reg: dict, sig: str, step: int,
                     run_has_fix: bool) -> dict:
    """What the orchestrator may do about a failure, bounded."""
    e = reg.get("entries", {}).get(sig)
    if e is None:
        return {"action": "diagnose",
                "why": "new signature; diagnose, fix on a branch, "
                       "full suite + harness claim, merge, record, "
                       "resume"}
    if e.get("status") == "fixed":
        if e.get("attempts", 0) >= MAX_HEAL_ATTEMPTS:
            return {"action": "pause",
                    "why": f"healing budget ({MAX_HEAL_ATTEMPTS}) spent "
                           f"on a signature believed fixed; escalate"}
        if not run_has_fix:
            return {"action": "pause",
                    "why": f"fix {e.get('fix_commit')} exists but the "
                           f"run does not contain it; re-dispatch "
                           f"would re-fail"}
        return {"action": "redispatch", "why": "known failure, fix "
                "present in the run; one bounded re-dispatch"}
    return {"action": "pause",
            "why": "signature already open; healing in progress, do "
                   "not double-spend the budget"}
