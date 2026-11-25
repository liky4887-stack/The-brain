"""Tests for canonical factory records (Stage 1 data foundation).

A small bakery factory (the F&B MVP rehearsal) exercises reference
integrity, per-record validation, and the frePPLe table mapping. The
frePPLe row shapes are locked against frePPLe's import CSV column
names (schema contract only; no frePPLe code involved).
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.records import (
    Buffer, Calendar, Demand, Factory, Item, Location, Operation,
    OperationMaterial, OperationResource, Resource, SetupMatrix, SetupRule,
    frepple_rows,
)


def bakery() -> Factory:
    return Factory(
        locations=[Location(name="Bakery")],
        items=[Item(name="Flour"), Item(name="Bread")],
        calendars=[Calendar(
            name="LineHours",
            buckets=[(datetime(2026, 11, 25, 6), datetime(2026, 11, 25, 22), 1.0)],
        )],
        setup_matrices=[SetupMatrix(name="OvenSM", rules=[
            SetupRule(from_setup="White", to_setup="Brown",
                      duration=timedelta(minutes=30)),
        ])],
        resources=[Resource(name="Oven1", location="Bakery", maximum=1.0,
                            maximum_calendar="LineHours", setup_matrix="OvenSM")],
        operations=[Operation(
            name="BakeBread", item="Bread", location="Bakery",
            duration=timedelta(minutes=45), size_minimum=1.0, size_maximum=100.0,
            materials=[OperationMaterial(item="Flour", quantity=-0.5),
                       OperationMaterial(item="Bread", quantity=1.0)],
            loads=[OperationResource(resource="Oven1", quantity=1.0, setup="White")],
        )],
        buffers=[Buffer(item="Flour", location="Bakery", onhand=200.0),
                 Buffer(item="Bread", location="Bakery", onhand=0.0)],
        demands=[Demand(name="Order-1", item="Bread", location="Bakery",
                        due=datetime(2026, 11, 26, 8), quantity=80.0)],
    )


def test_bakery_is_clean():
    assert bakery().validate_references() == []


def test_producing_operations_lookup():
    f = bakery()
    assert [op.name for op in f.producing_operations("Bread")] == ["BakeBread"]
    assert f.producing_operations("Flour") == []


def test_broken_references_all_reported():
    f = bakery()
    f.demands.append(Demand(name="Ghost", item="Cake",
                            due=datetime(2026, 11, 26), quantity=5))
    f.operations.append(Operation(name="Knead", loads=[
        OperationResource(resource="Mixer9")]))
    f.buffers.append(Buffer(item="Yeast", location="Cellar"))
    problems = f.validate_references()
    assert any("Ghost: unknown item Cake" in p for p in problems)
    assert any("Knead: unknown resource Mixer9" in p for p in problems)
    assert any("unknown item" in p and "Yeast" in p for p in problems)
    assert any("unknown location" in p and "Cellar" in p for p in problems)


def test_record_level_validation():
    with pytest.raises(ValueError):
        Demand(name="D", item="X", due=datetime(2026, 1, 1), quantity=0)
    with pytest.raises(ValueError):
        Operation(name="O", size_minimum=10, size_maximum=5)
    with pytest.raises(ValueError):
        Buffer(item="X", location="L", onhand=-1)
    with pytest.raises(ValueError):
        Calendar(name="C", buckets=[(datetime(2026, 1, 1, 6),
                                     datetime(2026, 1, 1, 4), 1.0)])
    with pytest.raises(ValueError):
        SetupRule(from_setup="A", to_setup="B", duration=timedelta(minutes=-5))


def test_setup_matrix_lookup_and_missing():
    m = bakery().setup_matrices[0]
    assert m.duration_between("White", "Brown") == timedelta(minutes=30)
    assert m.duration_between("White", "White") == timedelta(0)
    assert m.duration_between("Brown", "White") is None


def test_frepple_rows_locked_shape():
    rows = frepple_rows(bakery())
    assert set(rows) == {"location", "item", "calendar", "setupmatrix",
                         "setuprule", "resource", "operation",
                         "operationmaterial", "operationresource",
                         "buffer", "demand"}
    op = rows["operation"][0]
    assert op["name"] == "BakeBread" and op["duration"] == "0:45:00"
    assert op["sizemaximum"] == 100.0
    mat = rows["operationmaterial"][0]
    assert mat == {"operation": "BakeBread", "item": "Flour", "quantity": -0.5}
    rule = rows["setuprule"][0]
    assert rule["duration"] == "0:30:00" and rule["setupmatrix"] == "OvenSM"
    dem = rows["demand"][0]
    assert dem["due"] == "2026-11-26T08:00:00" and dem["priority"] == 1
