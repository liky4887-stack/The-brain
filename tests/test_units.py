"""Units of measure: one unit per item, mixed-unit rows rejected, no silent conversion."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))
from brain_core.ingest import load_csvs, ERROR_W, build_data_error_report  # noqa: E402


def _w(d, n, t):
    (d / n).write_text(t)


def _base(d, items, demands, buffers=None):
    _w(d, "items.csv", items)
    _w(d, "locations.csv", "name\nL1\n")
    _w(d, "demands.csv", demands)
    if buffers is not None:
        _w(d, "buffers.csv", buffers)


def test_demand_in_other_unit_than_declared_is_rejected(tmp_path):
    _base(tmp_path, "name,unit\nMILK,L\n",
          "name,item,due,quantity,unit\nD1,MILK,2026-01-02,100,L\nD2,MILK,2026-01-03,5,gal\n")
    r = load_csvs(tmp_path)
    errs = [f for f in r.findings if f.code == "unit-mismatch"]
    assert len(errs) == 1 and errs[0].table == "demands" and errs[0].row == 2
    assert "'gal'" in errs[0].detail and "'L'" in errs[0].detail
    assert [d.name for d in r.factory.demands] == ["D1"]       # not coerced, not summed
    assert r.score == 100 - ERROR_W


def test_buffer_vs_demand_unit_comparison_is_rejected(tmp_path):
    _base(tmp_path, "name,unit\nFLOUR,kg\n",
          "name,item,due,quantity,unit\nD1,FLOUR,2026-01-02,100,kg\n",
          "item,location,onhand,unit\nFLOUR,L1,50,g\n")
    r = load_csvs(tmp_path)
    codes = [(f.code, f.table) for f in r.findings]
    assert ("unit-mismatch", "buffers") in codes             # kg vs g is NOT rescaled
    assert r.factory.buffers == []


def test_undeclared_item_first_unit_seen_defines_it(tmp_path):
    _base(tmp_path, "name\nEGG\n",
          "name,item,due,quantity,unit\nD1,EGG,2026-01-02,10,dozen\nD2,EGG,2026-01-03,10,piece\n")
    r = load_csvs(tmp_path)
    bad = [f for f in r.findings if f.code == "unit-mismatch"]
    assert len(bad) == 1 and bad[0].row == 2 and "first seen" in bad[0].detail


def test_no_units_anywhere_changes_nothing(tmp_path):
    _base(tmp_path, "name\nEGG\n", "name,item,due,quantity\nD1,EGG,2026-01-02,10\n")
    r = load_csvs(tmp_path)
    assert r.findings == [] and r.score == 100.0


def test_items_without_unit_are_counted_not_silently_skipped(tmp_path):
    _base(tmp_path, "name,unit\nMILK,L\nSALT,\n",
          "name,item,due,quantity,unit\nD1,MILK,2026-01-02,10,L\n")
    r = load_csvs(tmp_path)
    info = [f for f in r.findings if f.code == "units-not-declared"]
    assert len(info) == 1 and info[0].severity == "info" and "SALT" in info[0].detail
    assert r.score == 100.0                                   # info is not scored


def test_unit_mismatch_is_in_the_data_error_report_with_file_line(tmp_path):
    _base(tmp_path, "name,unit\nMILK,L\n",
          "name,item,due,quantity,unit\nD1,MILK,2026-01-02,100,L\nD2,MILK,2026-01-03,5,gal\n")
    rep = build_data_error_report(load_csvs(tmp_path), tmp_path)
    e = [x for x in rep.entries if x.code == "unit-mismatch"][0]
    assert (e.sources[0].file, e.sources[0].line) == ("demands.csv", 3)


def test_item_unit_roundtrips_through_dump_and_load(tmp_path):
    from brain_core.ingest import dump_csvs
    from brain_core.synthetic import FnbParams, generate_fnb_factory
    p = generate_fnb_factory(FnbParams(seed=3, n_lines=2, n_skus=6, days=3,
                                       active_fraction=0.9, utilization=0.5,
                                       n_raw_materials=3,
                                       families=("DAIRY", "BAKERY")))
    f = p.factory
    f = f.model_copy(update={"items": [i.model_copy(update={"unit": "kg"}) for i in f.items]})
    dump_csvs(f, tmp_path)
    r = load_csvs(tmp_path)
    assert r.findings == [] and {i.unit for i in r.factory.items} == {"kg"}
