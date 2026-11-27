"""Per-run data-error report: problems trace to source CSV rows."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))
from brain_core.ingest import load_csvs, build_data_error_report, index_sources  # noqa: E402


def _write(d, name, text):
    (d / name).write_text(text)


def _dir(tmp_path):
    _write(tmp_path, "items.csv", "name,cost\nMILK-1L,1\nBREAD-9,2\n")
    _write(tmp_path, "resources.csv", "name\nLINE-A\nLINE-B\n")
    _write(tmp_path, "demands.csv",
           "name,item,due,quantity\nD1,MILK-1L,2026-01-02,100\nD2,BREAD-9,not-a-date,50\n")
    return tmp_path


def test_ingest_finding_carries_file_and_line(tmp_path):
    d = _dir(tmp_path)
    rep = build_data_error_report(load_csvs(d), d)
    bad = [e for e in rep.entries if e.code == "bad-date"]
    assert len(bad) == 1
    s = bad[0].sources[0]
    assert (s.file, s.row, s.line) == ("demands.csv", 2, 3)   # header is line 1


def test_validator_problem_traces_to_resource_and_item_rows(tmp_path):
    d = _dir(tmp_path)
    rep = build_data_error_report(
        load_csvs(d), d,
        validator_problems=["LINE-B day 2: BREAD-9 not eligible on LINE-B"])
    e = [x for x in rep.entries if x.origin == "validator"][0]
    got = {(s.file, s.line) for s in e.sources}
    assert got == {("resources.csv", 3), ("items.csv", 3)}, got
    assert e.method == "name-match"
    assert rep.unattributed == 0


def test_unmatched_problem_is_kept_and_counted_not_dropped(tmp_path):
    d = _dir(tmp_path)
    rep = build_data_error_report(load_csvs(d), d,
                                  solver_problems=["window infeasible: need exceeds capacity"])
    e = [x for x in rep.entries if x.origin == "solver"][0]
    assert e.sources == () and e.method == "none"
    assert rep.unattributed == 1


def test_name_must_be_whole_token(tmp_path):
    d = _dir(tmp_path)
    rep = build_data_error_report(load_csvs(d), d,
                                  validator_problems=["LINE-AB day 1: overloaded"])
    assert rep.entries[-1].sources == ()      # LINE-AB is not LINE-A


def test_render_and_dict_are_consistent(tmp_path):
    d = _dir(tmp_path)
    rep = build_data_error_report(load_csvs(d), d,
                                  validator_problems=["LINE-A day 1: overloaded"])
    assert "resources.csv:2" in rep.render()
    assert rep.to_dict()["counts"]["validator"] == 1
    assert index_sources(d).lookup("resources", "LINE-A")[0].line == 2
