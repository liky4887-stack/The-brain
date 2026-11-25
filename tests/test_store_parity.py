"""Tests for the records store (Stage 1) and the frePPLe parity check.

The frePPLe parity test is the schema-contract half of the ROADMAP
"same plan in frePPLe and the compiler" gate: the same Factory feeds
both the compiler and the frePPLe table export, and the exported
column names are locked against frePPLe's own model definitions
(freppledb/input/models/*.py, frePPLe 9.x dev tree, Nov 2026; AGPL —
names only, no code). Running the full frePPLe planner side-by-side
needs a frePPLe deployment and stays an environment check, flagged
honestly here.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.compiler import compile_jobshop, compile_lotsizing
from brain_core.records import frepple_rows
from brain_core.records.store import load, save
from tests.test_records import bakery  # the F&B rehearsal factory


def test_store_roundtrip(tmp_path):
    db = str(tmp_path / "factory.db")
    save(bakery(), db)
    back = load(db)
    assert back.validate_references() == []
    def canon(f):
        d = f.model_dump()
        for op in d["operations"]:
            op["materials"].sort(key=lambda m: m["item"])
        return d
    assert canon(back) == canon(bakery())


def test_store_refuses_broken_factory(tmp_path):
    f = bakery()
    f.demands.append(Demand_(name="Ghost", item="Cake",
                             due=datetime(2026, 11, 26), quantity=5))
    with pytest.raises(ValueError, match="broken references"):
        save(f, str(tmp_path / "bad.db"))


def Demand_(**kw):  # local alias keeps the import list honest
    from brain_core.records import Demand
    return Demand(**kw)


def test_store_load_revalidates(tmp_path):
    db = str(tmp_path / "factory.db")
    save(bakery(), db)
    import sqlite3
    con = sqlite3.connect(db)
    con.execute("INSERT INTO demand VALUES (?,?,?,?,?,?,?,?)",
                ("Bad", "NoSuchItem", None, "2026-11-26T00:00:00", 1.0, 1,
                 None, None))
    con.commit()
    con.close()
    with pytest.raises(ValueError, match="broken references"):
        load(db)


# frePPLe parity: column names locked from frePPLe's model definitions
FREPPLE_COLUMNS = {
    "location": {"name", "description", "available"},
    "item": {"name", "description", "cost"},
    "resource": {"name", "location", "maximum", "maximum_calendar",
                 "setupmatrix", "efficiency"},
    "operation": {"name", "item", "location", "duration", "duration_per",
                  "sizeminimum", "sizemultiple", "sizemaximum", "cost"},
    "operationmaterial": {"operation", "item", "quantity"},
    "operationresource": {"operation", "resource", "quantity", "setup",
                          "skill"},
    "buffer": {"item", "location", "onhand", "minimum", "maximum"},
    "demand": {"name", "item", "location", "due", "quantity", "priority",
               "minshipment", "maxlateness"},
    "setupmatrix": {"name"},
    "setuprule": {"setupmatrix", "fromsetup", "tosetup", "duration", "cost"},
    "calendar": {"name", "default"},
}


def test_frepple_export_columns_match_frepple_schema():
    rows = frepple_rows(bakery())
    for table, cols in FREPPLE_COLUMNS.items():
        assert table in rows
        if rows[table]:
            assert set(rows[table][0]) <= cols | set(rows[table][0]), table
            assert set(rows[table][0]) == cols, (
                f"{table}: exported {sorted(rows[table][0])}, "
                f"frePPLe has {sorted(cols)}")


def test_same_factory_feeds_compiler_and_frepple_export():
    f = bakery()
    rows = frepple_rows(f)
    # the demand the compiler schedules is the demand frePPLe would show
    assert rows["demand"][0]["name"] == "Order-1"
    assert rows["demand"][0]["quantity"] == 80.0
    # compiler sees exactly one job for it on the one loaded resource
    c = compile_jobshop(f)
    assert c.job_names == ("Order-1",)
    assert c.instance.routes[0][0][0] == "Oven1"
    # lot-sizing template agrees on the quantity
    periods = [datetime(2026, 11, 25) + t * timedelta(days=1)
               for t in range(3)]
    ls = compile_lotsizing(f, "Bread", periods, timedelta(days=1),
                           setup_cost=10.0, holding_cost=1.0)
    assert sum(ls.demands) == 80.0
