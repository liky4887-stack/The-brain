"""The six independent checkpoints (docs/COMPLETION-VERIFICATION.md).

Every check returns (status, evidence): status in PASS / FAIL /
BLOCKED. BLOCKED means the check could not run - it is reported, never
converted into a pass. Checks are ordered but independent: each takes
the claim + a repo path and verifies ONE kind of real state.

Command injection seam: subprocess calls go through `run` so tests can
substitute a fake without touching the network, git, or the suite.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"


def run(cmd: list[str], cwd: str | None = None,
        timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


def check_remote_state(claim, repo: str, runner=run):
    """Claimed SHA must equal the remote branch head right now."""
    try:
        r = runner(["git", "ls-remote", claim.remote,
                    f"refs/heads/{claim.branch}"], cwd=repo, timeout=60)
    except Exception as e:
        return BLOCKED, {"why": f"ls-remote could not run: {e}"}
    if r.returncode != 0 or not r.stdout.strip():
        return BLOCKED, {"why": "ls-remote returned nothing",
                         "stderr": r.stderr[-300:]}
    remote_sha = r.stdout.split()[0]
    ok = remote_sha == claim.sha
    return (PASS if ok else FAIL), {
        "claimed": claim.sha, "remote_head": remote_sha,
        "why": "" if ok else "claimed SHA is not the remote head - the "
                             "'merged' claim did not land (or landed later)"}


def check_clean_room_suite(claim, repo: str, runner=run,
                           suite_cmd: list[str] | None = None,
                           workdir: str | None = None):
    """The suite ACTUALLY runs on a fresh clone of the claimed SHA in a
    fresh venv (labelled: clean-room venv, not a container - this host
    has no docker). Parsed counts must match the claim."""
    import tempfile
    suite_cmd = suite_cmd or ["python", "-m", "pytest", "-q",
                              "-m", "not benchmark"]
    tmp = workdir or tempfile.mkdtemp(prefix="verify-cleanroom-")
    steps = []
    try:
        r = runner(["git", "clone", "-q", repo, tmp], timeout=300)
        steps.append(("clone", r.returncode))
        if r.returncode != 0:
            return FAIL, {"why": "clone failed", "stderr": r.stderr[-300:]}
        r = runner(["git", "checkout", "-q", claim.sha], cwd=tmp,
                   timeout=120)
        steps.append(("checkout", r.returncode))
        if r.returncode != 0:
            return FAIL, {"why": f"claimed SHA {claim.sha} not present "
                                 "in a fresh clone",
                          "stderr": r.stderr[-300:]}
        r = runner(["python", "-m", "venv", ".venv"], cwd=tmp,
                   timeout=300)
        steps.append(("venv", r.returncode))
        if r.returncode != 0:
            return BLOCKED, {"why": "venv creation failed",
                             "stderr": r.stderr[-300:]}
        pip = os.path.join(tmp, ".venv", "bin", "pip")
        r = runner([pip, "install", "-q", "-e",
                    "packages/brain-core", "pytest"],
                   cwd=tmp, timeout=900)
        steps.append(("install", r.returncode))
        if r.returncode != 0:
            return BLOCKED, {"why": "dependency install failed",
                             "stderr": r.stderr[-300:]}
        py = os.path.join(tmp, ".venv", "bin", "python")
        cmd = [py if c == "python" else c for c in suite_cmd]
        r = runner(cmd, cwd=tmp, timeout=1800)
        steps.append(("suite", r.returncode))
        m = re.search(r"(\d+) passed(?:, (\d+) skipped)?",
                      r.stdout + r.stderr)
        parsed = {"passed": int(m.group(1)) if m else None,
                  "skipped": int(m.group(2)) if m and m.group(2) else 0}
        if not m:
            return FAIL, {"why": "suite output unparsable (did tests "
                                 "actually run?)", "steps": steps,
                          "tail": (r.stdout + r.stderr)[-300:]}
        ev = {"room": "clean-room venv (no docker on host - labelled "
                      "substitute)", "steps": steps, "parsed": parsed,
              "claimed": claim.tests}
        if claim.tests:
            ok = (parsed["passed"] == claim.tests.get("passed")
                  and r.returncode == 0)
            if not ok:
                ev["why"] = ("real run disagrees with the claim - the "
                             "claimed test counts are fabricated or stale")
            return (PASS if ok else FAIL), ev
        return (PASS if r.returncode == 0 else FAIL), ev
    except subprocess.TimeoutExpired as e:
        return BLOCKED, {"why": f"timeout: {e}", "steps": steps}


def check_artifacts_exist(claim, repo: str, runner=run):
    """Every claimed artifact exists, is non-empty, and parses.
    'branch:path' artifacts are read via git show."""
    missing, seen = [], []
    for a in claim.artifacts:
        if ":" in a and not os.path.isabs(a) and "/" not in a.split(":")[0]:
            ref, path = a.split(":", 1)
            r = runner(["git", "show", f"{ref}:{path}"], cwd=repo,
                       timeout=60)
            content = r.stdout if r.returncode == 0 else None
        else:
            content = open(a).read() if os.path.isfile(a) else None
        if not content:
            missing.append(a)
            continue
        if a.endswith(".json"):
            try:
                json.loads(content)
            except json.JSONDecodeError:
                missing.append(f"{a} (unparsable JSON)")
                continue
        seen.append(a)
    ok = not missing
    return (PASS if ok else FAIL), {"found": seen, "missing": missing,
        "why": "" if ok else "claimed evidence does not exist - the "
                             "claim cites artifacts that were never written"}


def check_numbers_recomputed(claim, repo: str, runner=run):
    """The claim's recompute command is run for real; named numbers are
    compared. The claim's numbers never stand on the claimant's word."""
    if claim.recompute is None:
        return PASS, {"note": "no recompute command claimed"}
    rc = claim.recompute
    try:
        r = runner(["bash", "-c", rc.cmd], cwd=repo, timeout=1800)
    except subprocess.TimeoutExpired:
        return BLOCKED, {"why": "recompute timed out"}
    if r.returncode != 0:
        return FAIL, {"why": "recompute command failed",
                      "stderr": r.stderr[-300:]}
    try:
        got = json.loads(r.stdout)
    except json.JSONDecodeError:
        return FAIL, {"why": "recompute output is not JSON",
                      "tail": r.stdout[-300:]}
    diffs = {}
    for k, want in rc.expect.items():
        have = got.get(k)
        if isinstance(want, (int, float)) and isinstance(have, (int, float)):
            if abs(have - want) > rc.tolerance:
                diffs[k] = {"claimed": want, "recomputed": have}
        elif have != want:
            diffs[k] = {"claimed": want, "recomputed": have}
    return (FAIL if diffs else PASS), {
        "compared": sorted(rc.expect), "diffs": diffs,
        "why": "recomputed numbers disagree with the claim" if diffs else ""}


_LABEL_RE = re.compile(r"\b\d[\d,\.]*\b")
_TAG_RE = re.compile(r"\b(MEASURED|EXTRAPOLATED|ESTIMATED)\b")
_PLACEHOLDER_RE = re.compile(
    r"TODO|FIXME|NotImplementedError|placeholder|lorem ipsum|\bdummy\b"
    r"|\bfake\b|XXX", re.I)


def check_labels_present(claim, repo: str, **_):
    """Every quantitative claim in the report carries a
    MEASURED/EXTRAPOLATED/ESTIMATED label on its line; UNKNOWN is never
    reported as infeasible/impossible."""
    if not claim.report_file:
        return PASS, {"note": "no report file claimed"}
    if not os.path.isfile(os.path.join(repo, claim.report_file)):
        return FAIL, {"why": f"report {claim.report_file} missing"}
    text = open(os.path.join(repo, claim.report_file)).read()
    bad_lines = [ln.strip()[:120] for ln in text.splitlines()
                 if _LABEL_RE.search(ln) and not _TAG_RE.search(ln)
                 and not ln.strip().startswith(("#", "- #"))]
    dishonest = [ln.strip()[:120] for ln in text.splitlines()
                 if re.search(r"UNKNOWN", ln)
                 and re.search(r"infeasible|impossible|cannot be solved",
                               ln, re.I)]
    ok = not bad_lines and not dishonest
    return (PASS if ok else FAIL), {
        "unlabelled_number_lines": bad_lines[:10],
        "unknown_misreported": dishonest[:10],
        "why": "" if ok else "numbers without MEASURED/EXTRAPOLATED "
                             "labels, or UNKNOWN sold as infeasible"}


def check_no_placeholder(claim, repo: str, **_):
    """Claimed deliverable files contain no placeholder/fake markers."""
    hits = {}
    for d in claim.deliverables:
        path = os.path.join(repo, d)
        if not os.path.isfile(path):
            hits[d] = ["FILE MISSING"]
            continue
        text = open(path, errors="replace").read()
        found = sorted(set(m.group(0) for m in
                           _PLACEHOLDER_RE.finditer(text)))
        if found:
            hits[d] = found
    ok = not hits
    return (PASS if ok else FAIL), {"hits": hits,
        "why": "" if ok else "placeholder/fake markers in claimed "
                             "deliverables"}
