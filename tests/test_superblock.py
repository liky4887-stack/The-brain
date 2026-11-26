"""Super-block aggregation (benchmarks/superblock.py): provenance,
disjointness, recomputation, cross-block consistency, verdict rules.
"""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from superblock import aggregate


def block(run_id, offset, plants, verdict="PASS", mean_solve=500.0,
          missing=None, n_problems=0, vars_per_plant=69000):
    return {
        "verdict": verdict,
        "shards_missing": missing or [],
        "measured": {
            "plants": plants,
            "aggregate_vars": vars_per_plant * plants,
            "aggregate_rows": 24000 * plants,
            "aggregate_binaries": 8000 * plants,
            "windows": 2 * plants,
            "assignments_validated": 325 * plants,
            "n_validation_problems": n_problems,
            "per_plant_solve_s": {"min": 100.0, "mean": mean_solve,
                                  "max": 900.0},
            "distributed_wall_s": 3000.0,
            "merge_validate_s": 400.0,
            "kpis": {"changeover_minutes": 1000.0 * plants,
                     "backlog_units_end": 1e-9},
        },
        "ladder": {"step": 7, "plants": plants, "shards": 256,
                   "run_id": str(run_id), "sha": "abc123",
                   "plant_offset": offset},
    }


def test_two_blocks_pass_and_resum():
    a = block("1", 0, 2048)
    b = block("2", 2048, 2048)
    out = aggregate([a, b])
    assert out["verdict"] == "PASS"
    m = out["measured"]
    assert m["plants"] == 4096
    assert m["vars"] == 2 * 69000 * 2048
    assert m["assignments"] == 2 * 325 * 2048
    assert m["distributed_wall_s"] == 6000.0
    assert out["label"].startswith("MEASURED")
    assert [bl["plant_range"] for bl in out["blocks"]] == [[0, 2048],
                                                           [2048, 4096]]


def test_overlapping_ranges_open():
    a = block("1", 0, 2048)
    b = block("2", 1024, 2048)
    out = aggregate([a, b])
    assert out["verdict"] == "OPEN"
    assert any("overlap" in p for p in out["problems"])


def test_duplicate_run_id_open():
    a = block("1", 0, 2048)
    b = block("1", 2048, 2048)
    out = aggregate([a, b])
    assert out["verdict"] == "OPEN"
    assert any("run ids not distinct" in p for p in out["problems"])


def test_open_block_propagates():
    a = block("1", 0, 2048)
    b = block("2", 2048, 2048, verdict="OPEN")
    out = aggregate([a, b])
    assert out["verdict"] == "OPEN"
    assert any("verdict OPEN" in p for p in out["problems"])


def test_missing_shards_and_problems_propagate():
    a = block("1", 0, 2048, missing=[3])
    b = block("2", 2048, 2048, n_problems=2)
    out = aggregate([a, b])
    assert out["verdict"] == "OPEN"
    assert any("missing shards" in p for p in out["problems"])
    assert any("validation problems" in p for p in out["problems"])


def test_missing_provenance_open():
    a = block("1", 0, 2048)
    b = copy.deepcopy(block("2", 2048, 2048))
    del b["ladder"]["run_id"]
    out = aggregate([a, b])
    assert out["verdict"] == "OPEN"
    assert any("provenance" in p for p in out["problems"])


def test_consistency_flag_on_drifted_block():
    a = block("1", 0, 2048, mean_solve=500.0)
    b = block("2", 2048, 2048, mean_solve=500.0)
    c = block("3", 4096, 2048, mean_solve=1400.0)  # drifted environment
    out = aggregate([a, b, c])
    assert out["verdict"] == "OPEN"
    assert any("drift" in p for p in out["problems"])
    # same three without the drift passes
    c2 = block("3", 4096, 2048, mean_solve=520.0)
    assert aggregate([a, b, c2])["verdict"] == "PASS"


def test_chain_appends_tail_to_head():
    from superblock import extend_chain
    chain = extend_chain(None, block("1", 0, 2048))
    assert chain["verdict"] == "PASS"
    chain = extend_chain(chain, block("2", 2048, 2048))
    assert chain["verdict"] == "PASS"
    assert chain["chain"]["plant_span"] == [0, 4096]
    assert chain["chain"]["ordered_run_ids"] == ["1", "2"]
    assert chain["measured"]["plants"] == 4096
    # one final output carries the full ordered provenance
    assert [b["ladder"]["run_id"] for b in chain["blocks_raw"]] == ["1", "2"]


def test_chain_rejects_gap_and_reorder():
    from superblock import extend_chain
    chain = extend_chain(None, block("1", 0, 2048))
    gap = extend_chain(chain, block("2", 4096, 2048))   # gap at [2048,4096)
    assert gap["verdict"] == "OPEN"
    assert any("chain break" in p for p in gap["problems"])
    dup = extend_chain(chain, block("2", 0, 2048))      # reorder/repeat
    assert dup["verdict"] == "OPEN"


def test_chain_rejects_bad_first_block():
    from superblock import extend_chain
    out = extend_chain(None, block("1", 2048, 2048))    # must start at 0
    assert out["verdict"] == "OPEN"
    assert any("chain break" in p for p in out["problems"])
