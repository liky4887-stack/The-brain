"""Stage 2, slice 3: CSV ingestion of canonical records.

Round-trip contract (dump -> load is lossless, score 100), tolerant
parsing of a dirty ERP export (bad rows skipped with findings, never
coerced silently), and the documented score arithmetic.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.ingest import (ERROR_W, WARN_W, dump_csvs, load_csvs)
from brain_core.records.models import (Demand, Factory, Item, Operation,
                                       OperationResource, Resource,
                                       SetupMatrix, SetupRule)
from brain_core.synthetic import FnbParams, generate_fnb_factory

from datetime import datetime, timedelta


def _sorted(factory):
    """Canonical form for equality: every record list sorted by name."""
    d = factory.model_dump()
    for key in ("locations", "items", "setup_matrices", "resources",
                "operations", "demands"):
        d[key] = sorted(d[key], key=lambda r: r["name"])
    d["buffers"] = sorted(d["buffers"],
                          key=lambda r: (r["item"], r["location"]))
    return d


def test_roundtrip_small_synthetic_plant(tmp_path):
    p = generate_fnb_factory(FnbParams(seed=3, n_lines=2, n_skus=12,
                                       days=3, active_fraction=0.9,
                                       utilization=0.5, n_raw_materials=4,
                                       families=("DAIRY", "BAKERY")))
    dump_csvs(p.factory, tmp_path)
    report = load_csvs(tmp_path)
    assert report.factory is not None
    assert report.findings == [], [f.detail for f in report.findings]
    assert report.score == 100.0
    assert _sorted(report.factory) == _sorted(p.factory)


def test_roundtrip_gate_schema_tables_all_written(tmp_path):
    p = generate_fnb_factory(FnbParams(seed=5, n_lines=3, n_skus=40,
                                       days=4, n_raw_materials=5,
                                       families=("DAIRY", "BAKERY",
                                                 "SAUCE")))
    dump_csvs(p.factory, tmp_path)
    for fname in ("items.csv", "resources.csv", "setuprules.csv",
                  "operations.csv", "operationloads.csv",
                  "operationmaterials.csv", "buffers.csv", "demands.csv"):
        assert (tmp_path / fname).exists(), fname


def _write_minimal(dirpath):
    (dirpath / "items.csv").write_text(
        "name,description,cost\nA,,0\nB,,0\n")
    (dirpath / "resources.csv").write_text(
        "name,location,maximum,efficiency,setupmatrix\nL1,,1,1,CHG\n")
    (dirpath / "setuprules.csv").write_text(
        "matrix,fromsetup,tosetup,duration_min,cost\n"
        "CHG,S1,S2,30,0\n")
    (dirpath / "operations.csv").write_text(
        "name,item,location,duration_min,duration_per_min,size_minimum,"
        "cost\nMAKE-A,A,,0,1,1,0\nMAKE-B,B,,0,1,1,0\n")
    (dirpath / "operationloads.csv").write_text(
        "operation,resource,quantity,setup\n"
        "MAKE-A,L1,1,S1\nMAKE-B,L1,1,S2\n")
    (dirpath / "demands.csv").write_text(
        "name,item,due,quantity,location,priority\n"
        "D1,A,2026-12-01,10,,1\n")


def test_clean_minimal_export_scores_100(tmp_path):
    _write_minimal(tmp_path)
    report = load_csvs(tmp_path)
    assert report.factory is not None
    assert report.score == 100.0
    assert report.findings == []
    assert len(report.factory.demands) == 1
    assert report.factory.demands[0].due == datetime(2026, 12, 1)


def test_dirty_export_skips_rows_and_scores(tmp_path):
    _write_minimal(tmp_path)
    (tmp_path / "demands.csv").write_text(
        "name,item,due,quantity,location,priority\n"
        "D1,A,2026-12-01,10,,1\n"
        "D2,A,not-a-date,5,,1\n"          # bad date -> skip
        "D3,NOPE,2026-12-01,5,,1\n"       # unknown item -> skip
        "D4,A,2026-12-02,-3,,1\n")        # negative qty -> pydantic skip
    (tmp_path / "items.csv").write_text(
        "name,description,cost\nA,,0\nB,,0\nA,,1\n")  # duplicate -> skip
    (tmp_path / "setuprules.csv").write_text(
        "matrix,fromsetup,tosetup,duration_min,cost\n"
        "CHG,S1,S2,30,0\n"
        "CHG,S2,S1,-5,0\n")               # negative duration -> skip
    report = load_csvs(tmp_path)
    assert report.factory is not None
    codes = sorted(f.code for f in report.findings)
    assert codes == ["bad-date", "duplicate-key", "invalid-row",
                     "negative-duration", "unknown-item"]
    assert all(f.severity == "error" for f in report.findings)
    assert report.score == 100 - 5 * ERROR_W
    kept = {d.name for d in report.factory.demands}
    assert kept == {"D1"}
    # surviving matrix has only the valid rule
    assert len(report.factory.setup_matrices[0].rules) == 1
    assert report.rows_read > report.rows_kept


def test_unknown_resource_load_dropped_operation_kept(tmp_path):
    _write_minimal(tmp_path)
    (tmp_path / "operationloads.csv").write_text(
        "operation,resource,quantity,setup\n"
        "MAKE-A,GHOST-LINE,1,S1\n"
        "MAKE-B,L1,1,S2\n")
    report = load_csvs(tmp_path)
    assert report.factory is not None  # not fatal
    codes = [f.code for f in report.findings]
    assert "unknown-resource" in codes
    assert "operation-without-load" in codes  # MAKE-A now loads nothing
    ops = {o.name: o for o in report.factory.operations}
    assert ops["MAKE-A"].loads == []
    assert len(ops["MAKE-B"].loads) == 1
    assert report.score == 100 - ERROR_W - WARN_W


def test_unknown_setup_state_is_warning_not_error(tmp_path):
    _write_minimal(tmp_path)
    (tmp_path / "operationloads.csv").write_text(
        "operation,resource,quantity,setup\n"
        "MAKE-A,L1,1,STATE-FROM-ANOTHER-PLANT\n"
        "MAKE-B,L1,1,S2\n")
    report = load_csvs(tmp_path)
    assert report.factory is not None
    [f] = [f for f in report.findings
           if f.code == "unknown-setup-state"]
    assert f.severity == "warning"
    assert report.score == 100 - WARN_W


def test_missing_tables_tolerated(tmp_path):
    (tmp_path / "items.csv").write_text("name,description,cost\nA,,0\n")
    report = load_csvs(tmp_path)
    assert report.factory is not None
    assert report.findings == []
    assert report.score == 100.0


def test_missing_required_column_is_an_error(tmp_path):
    (tmp_path / "demands.csv").write_text("name,item,quantity\nD1,A,5\n")
    report = load_csvs(tmp_path)
    [f] = report.findings
    assert f.code == "missing-column"
    assert f.severity == "error"
    assert report.score == 100 - ERROR_W


def test_score_floors_at_zero(tmp_path):
    (tmp_path / "items.csv").write_text(
        "name,description,cost\n" +
        "".join(f"I{k},,0\n" for k in range(25)) +
        "".join(f"I{k},,0\n" for k in range(25)))  # 25 duplicate keys
    report = load_csvs(tmp_path)
    assert report.score == 0.0  # 25 errors would be -125, floored
    assert len(report.factory.items) == 25
