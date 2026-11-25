"""Ceiling ladder: honest progression, honest stops."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.scale_ceiling import (LADDER, classify, next_action,
                                      write_config)


def measured(step, plants, shards, problems=0, verdict="PASS", **kw):
    r = {"verdict": verdict,
         "measured": {"plants": plants, "shards": shards,
                      "aggregate_vars": plants * 69200,
                      "aggregate_rows": plants * 24200,
                      "aggregate_binaries": plants * 8000,
                      "n_validation_problems": problems,
                      "validation_problems": ["plant 5: window 3 undecided"
                                              ] * problems,
                      "distributed_wall_s": 400.0 + step},
         "ladder": {"step": step, "plants": plants, "shards": shards}}
    r.update(kw)
    return r


def test_classify_real_schema():
    assert classify(measured(1, 192, 24))[0] == "PASS"
    st, reason = classify(measured(2, 384, 48, problems=2, verdict="OPEN"))
    assert st == "FAIL" and "undecided" in reason
    r = measured(2, 384, 48)
    r["measured"]["shards"] = 24          # only half the shards reported
    st, _ = classify(r)
    assert st == "FAIL"
    st, _ = classify({"verdict": "HARNESS-ERROR", "error": "boom"})
    assert st == "HARNESS-ERROR"


def test_ladder_progression_and_ceiling():
    # nothing measured: run step 1
    a = next_action([])
    assert a == {"action": "run", "step": 1, "plants": 192, "shards": 24,
                 "why": "step 1 not measured yet"}
    # step 1 pass: run step 2
    a = next_action([measured(1, 192, 24)])
    assert a["action"] == "run" and a["step"] == 2
    # step 2 fails: ceiling = measured step 1, with the failure reason
    a = next_action([measured(1, 192, 24),
                     measured(2, 384, 48, problems=1, verdict="OPEN")])
    assert a["action"] == "stop"
    assert a["ceiling"]["step"] == 1
    assert a["ceiling"]["variables"] == 192 * 69200
    assert a["ceiling"]["label"].startswith("MEASURED")
    assert a["failed_step"]["step"] == 2 and "undecided" in \
        a["failed_step"]["reason"]


def test_ladder_exhaustion_is_matrix_cap():
    hist = [measured(k, p, s)
            for k, (p, s) in enumerate(LADDER, start=1)]
    a = next_action(hist)
    assert a["action"] == "stop"
    assert a["ceiling"]["plants"] == 2048
    assert "matrix cap" in a["note"]
    assert LADDER[-1][1] <= 256  # never exceed the GitHub matrix cap


def test_harness_error_reruns_same_step():
    a = next_action([measured(1, 192, 24),
                     {"verdict": "HARNESS-ERROR", "error": "pip boom",
                      "ladder": {"step": 2, "plants": 384,
                                 "shards": 48}}])
    assert a["action"] == "rerun" and a["step"] == 2


def test_config_roundtrip(tmp_path):
    path = write_config(str(tmp_path), 3, 768, 96)
    cfg = json.load(open(path))
    assert (cfg["step"], cfg["plants"], cfg["shards"]) == (3, 768, 96)
