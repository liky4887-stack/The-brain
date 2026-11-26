#!/usr/bin/env python3
"""Ladder launch script (review: no long-lived launch branches with
stale code; every launch from current main with a preflight).

Guarantees:
- the launch ref (gate-scale/run) is recreated from CURRENT origin/main
  (delete + recreate: never a force push), so the run's code always
  contains main's latest plumbing;
- the plant range comes from the BLOCK TABLE below, never a manual
  flag: --block B means [2048, 4096), and the offset has no default;
- preflight: origin/main SHA fetched fresh, scale.yml on that SHA
  passes --plant-offset and --job-budget-s, config range matches the
  block; no launch if any check fails;
- the launch is appended to benchmarks/RUNS.md (one line per run).

Usage: python benchmarks/launch_scale.py --block B --step 7 \
           --run-id-note "retry of 45786313189"
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK_PLANTS = 2048
BLOCK_SHARDS = 256
RUNS_MD = os.path.join(REPO, "benchmarks", "RUNS.md")


def block_range(block: str) -> tuple[int, int]:
    """Block letter -> [offset, offset+plants). A=0..2047, B=2048..4095.
    No manual flags, no default offset: the letter IS the range."""
    if len(block) != 1 or not block.isalpha():
        raise SystemExit(f"bad block {block!r}: one letter A-Z")
    off = BLOCK_PLANTS * (ord(block.upper()) - ord("A"))
    return off, off + BLOCK_PLANTS


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                       **kw)
    if r.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n"
                         f"{r.stdout}\n{r.stderr}")
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", required=True)
    ap.add_argument("--step", type=int, required=True)
    ap.add_argument("--run-id-note", default="")
    ap.add_argument("--method", choices=["dispatch", "ref"],
                    default="dispatch",
                    help="dispatch: workflow_dispatch on main (needs the "
                         "default branch to be main); ref: legacy "
                         "delete+recreate of gate-scale/run")
    a = ap.parse_args()
    lo, hi = block_range(a.block)

    # preflight 1: fresh origin/main SHA
    sh(["git", "fetch", "-q", "origin", "main"])
    sha = sh(["git", "rev-parse", "origin/main"]).stdout.strip()

    # preflight 2: the workflow at that SHA passes the required flags
    wf = sh(["git", "show",
             f"{sha}:.github/workflows/scale.yml"]).stdout
    for flag in ("--plant-offset", "--job-budget-s", "canary",
                 "canary_real.py", "fail-fast: true"):
        if flag not in wf:
            raise SystemExit(f"preflight FAIL: scale.yml at {sha[:7]} "
                             f"lacks {flag}")

    # preflight 2b (review #12 pt1): F-rule lint of the exact SHA's tree
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        arc = subprocess.run(["git", "archive", sha], cwd=REPO,
                             capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", tmp], input=arc, check=True)
        lint = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--select",
             "F821,F822,F823,F632,F811,F402,F502,F504,F507,F509,F521,"
             "F522,F523,F524,F525,F701,F702,F704,F706,F707",
             "benchmarks", "packages", "tests"],
            cwd=tmp, capture_output=True, text=True)
        if lint.returncode != 0:
            raise SystemExit(f"preflight FAIL: lint errors at {sha[:7]}:\n"
                             f"{lint.stdout[-1500:]}{lint.stderr[-500:]}")

    # preflight 2c (review #12 pt5): CI (tests + lint, incl. the
    # checkpoint regression test) must be GREEN on this exact SHA
    import glob
    import urllib.request
    tok = glob.glob(os.path.expanduser("~/.vault/github-token-*/password"))
    if not tok:
        raise SystemExit("preflight FAIL: no token to verify CI status")
    token = open(tok[0]).read().strip()
    req = urllib.request.Request(
        "https://api.github.com/repos/liky4887-stack/The-brain/actions/"
        f"workflows/ci.yml/runs?head_sha={sha}",
        headers={"Authorization": f"Bearer {token}"})
    runs = json.load(urllib.request.urlopen(req)).get("workflow_runs", [])
    if not runs or runs[0].get("conclusion") != "success":
        state = (runs[0].get("status"), runs[0].get("conclusion")) \
            if runs else "no ci run"
        raise SystemExit(f"preflight FAIL: ci.yml not green on "
                         f"{sha[:7]} ({state}); wait for CI or fix")

    # preflight 3: config carries the block range exactly
    cfg_path = os.path.join(REPO, "config", "scale.json")
    cfg = {"step": a.step, "plants": BLOCK_PLANTS,
           "shards": BLOCK_SHARDS, "plant_offset": lo,
           "block": a.block.upper(),
           "note": f"ladder step {a.step} block {a.block.upper()}: "
                   f"plants [{lo}, {hi}); launched by "
                   "benchmarks/launch_scale.py from origin/main "
                   f"{sha[:12]} {a.run_id_note}".strip()}
    print("preflight OK:", json.dumps(cfg))

    if a.method == "dispatch":
        import glob
        import urllib.request
        tok_files = glob.glob(os.path.expanduser(
            "~/.vault/github-token-*/password"))
        if not tok_files:
            raise SystemExit("no vault token found for dispatch")
        token = open(tok_files[0]).read().strip()
        req = urllib.request.Request(
            "https://api.github.com/repos/liky4887-stack/The-brain/"
            "actions/workflows/scale.yml/dispatches",
            method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json"},
            data=json.dumps({"ref": "main",
                             "inputs": {"block": a.block.upper(),
                                        "step": str(a.step)}}).encode())
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 204, resp.status
        line = (f"| {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} "
                f"| (pending) | {sha[:12]} | ladder step {a.step} "
                f"block {a.block.upper()} | [{lo}, {hi}) | launched via "
                f"workflow_dispatch on main {a.run_id_note} |\n")
        with open(RUNS_MD, "a") as fh:
            fh.write(line)
        print("dispatched on main at", sha[:12], "- watch the run, "
              "then record its id over (pending) in RUNS.md")
        return

    # recreate the trigger ref from origin/main WITHOUT force push
    cur = sh(["git", "branch", "--show-current"]).stdout.strip()
    sh(["git", "push", "origin", "--delete", "gate-scale/run"],
       **{}) if subprocess.run(
           ["git", "ls-remote", "--exit-code", "origin",
            "gate-scale/run"], cwd=REPO,
           capture_output=True).returncode == 0 else None
    sh(["git", "checkout", "-q", "-B", "gate-scale/run",
        "origin/main"])
    json.dump(cfg, open(cfg_path, "w"), indent=1)
    sh(["git", "add", "config/scale.json"])
    sh(["git", "commit", "-q", "-m",
        f"Launch ladder step {a.step} block {a.block.upper()} "
        f"(plants [{lo}, {hi}), {BLOCK_SHARDS} shards) via "
        f"launch_scale.py preflight at origin/main {sha[:12]}"])
    env = dict(os.environ)
    env["GIT_ASKPASS"] = os.path.expanduser("~/git-askpass.sh")
    env["GIT_TERMINAL_PROMPT"] = "0"
    sh(["git", "push", "-q", "-u", "origin", "gate-scale/run"],
       env=env)
    new_sha = sh(["git", "rev-parse", "HEAD"]).stdout.strip()
    sh(["git", "checkout", "-q", cur or "main"])

    line = (f"| {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} "
            f"| (pending) | {new_sha[:12]} | ladder step {a.step} "
            f"block {a.block.upper()} | [{lo}, {hi}) | launched "
            f"{a.run_id_note} |\n")
    with open(RUNS_MD, "a") as fh:
        fh.write(line)
    print("launched at", new_sha[:12], "- watch the run, then record "
          "its id over (pending) in RUNS.md")


if __name__ == "__main__":
    main()
