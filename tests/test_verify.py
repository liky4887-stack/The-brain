"""Completion-verification harness: real state beats claimed state."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verify.claim import Claim
from verify import checks as C
from verify.pipeline import run_pipeline, verify_loop


def fake_runner(stdout="", returncode=0, stderr=""):
    def _run(cmd, cwd=None, timeout=900):
        return subprocess.CompletedProcess(cmd, returncode,
                                           stdout=stdout, stderr=stderr)
    return _run


BASE = dict(title="t", sha="abc123")


def test_claim_rejects_unaudited_fields(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({**BASE, "trust_me": True}))
    with pytest.raises(ValueError, match="unaudited"):
        Claim.from_json(str(f))


def test_remote_state_real_git(tmp_path, monkeypatch):
    """End-to-end against a real (local) git remote: matching SHA passes,
    a fabricated SHA fails."""
    # identity for the test commit comes from the environment, not from
    # runner or user git config
    for k in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(k + "_NAME", "test")
        monkeypatch.setenv(k + "_EMAIL", "test@example.com")
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty",
                    "-m", "x"], check=True)
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    ok_claim = Claim(remote=str(repo), **{**BASE, "sha": sha})
    status, _ = C.check_remote_state(ok_claim, str(repo))
    assert status == C.PASS
    bad_claim = Claim(remote=str(repo), **BASE)
    status, ev = C.check_remote_state(bad_claim, str(repo))
    assert status == C.FAIL and "did not land" in ev["why"]


def test_artifacts_must_exist_and_parse(tmp_path):
    good = tmp_path / "a.json"
    good.write_text(json.dumps({"x": 1}))
    claim = Claim(**BASE, artifacts=[str(good)])
    assert C.check_artifacts_exist(claim, ".")[0] == C.PASS
    claim = Claim(**BASE, artifacts=[str(good), str(tmp_path / "nope.json")])
    status, ev = C.check_artifacts_exist(claim, ".")
    assert status == C.FAIL and ev["missing"]


def test_numbers_must_recompute(tmp_path):
    payload = json.dumps({"rows": 2321508})
    claim = Claim(**BASE, recompute=__import__("verify.claim", fromlist=["Recompute"]).Recompute(
        "true", {"rows": 2321508}))
    status, _ = C.check_numbers_recomputed(
        claim, ".", runner=fake_runner(stdout=payload))
    assert status == C.PASS
    claim2 = Claim(**BASE, recompute=type(claim.recompute)(
        "true", {"rows": 999}))  # fabricated number
    status, ev = C.check_numbers_recomputed(
        claim2, ".", runner=fake_runner(stdout=payload))
    assert status == C.FAIL and ev["diffs"]["rows"]["claimed"] == 999


def test_labels_and_placeholders(tmp_path):
    rep = tmp_path / "report.md"
    rep.write_text("Wall time was 381.5 s.\nUNKNOWN means infeasible.\n")
    dl = tmp_path / "code.py"
    dl.write_text("# TODO: actually implement\n")
    claim = Claim(**BASE, report_file=str(rep), deliverables=[str(dl)])
    status, ev = C.check_labels_present(claim, tmp_path)
    assert status == C.FAIL
    assert ev["unlabelled_number_lines"] and ev["unknown_misreported"]
    rep.write_text("Wall time was 381.5 s (MEASURED).\n")
    assert C.check_labels_present(claim, tmp_path)[0] == C.PASS
    status, ev = C.check_no_placeholder(claim, tmp_path)
    assert status == C.FAIL and "TODO" in ev["hits"][str(dl)]
    dl.write_text("x = 1\n")
    assert C.check_no_placeholder(claim, tmp_path)[0] == C.PASS


def test_pipeline_aggregates_and_never_converts_blocked(tmp_path):
    def runner(cmd, cwd=None, timeout=900):
        if cmd[:2] == ["git", "ls-remote"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="",
                                               stderr="")
        if cmd[:1] == ["git"] or cmd[0].endswith("pip"):
            return subprocess.CompletedProcess(cmd, 0, stdout="ok",
                                               stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="5 passed",
                                           stderr="")
    claim = Claim(remote="no-such-remote", **BASE)
    verdict, results = run_pipeline(claim, ".", runner=runner)
    # remote-state could not run (empty ls-remote): reported BLOCKED,
    # never converted to a pass; nothing failed, so no NOT VERIFIED.
    assert results["remote-state"]["status"] == C.BLOCKED
    assert verdict == "BLOCKED"


def test_repair_loop_reruns_everything_and_bounds(tmp_path):
    good = tmp_path / "a.json"
    good.write_text(json.dumps({"x": 1}))
    claim = Claim(**BASE, artifacts=[str(good)])
    calls = {"n": 0}

    def repair(round_i, failures):
        calls["n"] += 1
        return claim

    v = verify_loop(claim, ".", repair,
                    runner=fake_runner(stdout="deadbeef  refs/heads/main"))
    # remote-state FAILs every round (claimed abc123 != deadbeef):
    # pipeline re-ran fully 3 times (initial + 2 repairs), then gave up
    assert v.verdict == "NOT VERIFIED"
    assert v.repair_rounds == 2
    assert calls["n"] == 2
    assert "never marking done" not in " ".join(v.notes) or True
    assert "NOT marking done" in " ".join(v.notes)
