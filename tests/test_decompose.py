"""Stage 4, slice 1: plant decomposition.

The partition must be PROVEN independent from the records: cells
share no SKU, sub-factories keep reference integrity, and anything
unassignable is reported, never dropped.
"""

import sys

import pytest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.decompose import partition_plants, sub_factory
from brain_core.records.models import (Demand, Factory, Item, Location,
                                       Operation, OperationMaterial,
                                       OperationResource, Resource,
                                       SetupMatrix, SetupRule)

H0 = datetime(2026, 11, 30)


def _op(name, item, lines):
    return Operation(
        name=name, item=item, location="P",
        duration_per=timedelta(minutes=1),
        materials=[OperationMaterial(item=item, quantity=1)],
        loads=[OperationResource(resource=l, setup=f"s{item}")
               for l in lines])


def _factory(line_skus, demands=()):
    """line_skus: {line: [skus that line can run]}."""
    lines = sorted(line_skus)
    skus = sorted({s for ss in line_skus.values() for s in ss})
    return Factory(
        locations=[Location(name="P")],
        items=[Item(name=s) for s in skus],
        resources=[Resource(name=l, location="P", setup_matrix="M")
                   for l in lines],
        setup_matrices=[SetupMatrix(name="M", rules=[
            SetupRule(from_setup=f"s{a}", to_setup=f"s{b}",
                      duration=timedelta(minutes=10))
            for a in skus for b in skus if a != b])],
        operations=[_op(f"make-{s}", s, [l for l in lines
                                         if s in line_skus[l]])
                    for s in skus],
        demands=list(demands))


def test_disjoint_lines_make_independent_cells():
    f = _factory({"L1": ["A"], "L2": ["B"]},
                 demands=[Demand(name="D1", item="A",
                                 due=H0 + timedelta(days=1),
                                 quantity=10.0),
                          Demand(name="D2", item="B",
                                 due=H0 + timedelta(days=1),
                                 quantity=20.0)])
    part = partition_plants(f)
    assert part.is_decomposable
    assert len(part.cells) == 2
    by_line = {c.lines[0]: c for c in part.cells}
    assert by_line["L1"].skus == ["A"]
    assert by_line["L2"].skus == ["B"]
    assert [d.name for d in by_line["L1"].demands] == ["D1"]
    assert [d.name for d in by_line["L2"].demands] == ["D2"]
    # sub-factories keep reference integrity
    for c in part.cells:
        assert sub_factory(f, c).validate_references() == []


def test_shared_sku_couples_lines_into_one_cell():
    f = _factory({"L1": ["A", "B"], "L2": ["B"]})
    part = partition_plants(f)
    assert not part.is_decomposable
    assert len(part.cells) == 1
    assert part.cells[0].lines == ["L1", "L2"]
    assert part.cells[0].skus == ["A", "B"]


def test_transitive_coupling_through_a_chain():
    f = _factory({"L1": ["A"], "L2": ["A", "B"], "L3": ["B"],
                  "L4": ["C"]})
    part = partition_plants(f)
    assert len(part.cells) == 2
    sizes = sorted(len(c.lines) for c in part.cells)
    assert sizes == [1, 3]


def test_unproducible_demand_is_reported_not_dropped():
    f = _factory({"L1": ["A"]},
                 demands=[Demand(name="GHOST", item="ZZZ",
                                 due=H0 + timedelta(days=1),
                                 quantity=5.0)])
    part = partition_plants(f)
    assert not part.is_decomposable
    assert len(part.problems) == 1
    assert "GHOST" in part.problems[0]
    assert "ZZZ" in part.problems[0]


def _solvable_two_cell_factory():
    """Two independent cells, each 1 line with 2 SKUs and real demand."""
    skus = ["A", "B", "C", "D"]
    return Factory(
        locations=[Location(name="P")],
        items=[Item(name=s) for s in skus],
        resources=[Resource(name="L1", location="P", setup_matrix="M"),
                   Resource(name="L2", location="P", setup_matrix="M")],
        setup_matrices=[SetupMatrix(name="M", rules=[
            SetupRule(from_setup=f"s{a}", to_setup=f"s{b}",
                      duration=timedelta(minutes=5))
            for a in skus for b in skus if a != b])],
        operations=[_op("make-A", "A", ["L1"]), _op("make-B", "B", ["L1"]),
                    _op("make-C", "C", ["L2"]), _op("make-D", "D", ["L2"])],
        demands=[Demand(name="DA", item="A", due=H0 + timedelta(days=1),
                        quantity=100.0),
                 Demand(name="DB", item="B", due=H0 + timedelta(days=2),
                        quantity=100.0),
                 Demand(name="DC", item="C", due=H0 + timedelta(days=1),
                        quantity=100.0),
                 Demand(name="DD", item="D", due=H0 + timedelta(days=2),
                        quantity=100.0)])


def test_solve_decomposed_merges_and_validates_on_full_factory():
    from brain_core.decompose import solve_decomposed
    f = _solvable_two_cell_factory()
    res = solve_decomposed(f, H0, days=2, cap_min=480.0,
                           bucket_time_s=5, seq_time_s=2)
    assert res.decomposed and res.cells == 2
    assert res.problems == [], res.problems[:4]
    # every demand served: no lateness measured on the merged plan
    assert res.kpis["backlog_units_end"] == pytest.approx(0.0)
    # all four SKUs produced
    made = {a.sku for a in res.plan.assignments}
    assert made == {"A", "B", "C", "D"}
    # each assignment stays on its SKU's only line
    for a in res.plan.assignments:
        assert (a.sku in {"A", "B"}) == (a.line == "L1")


def test_solve_decomposed_refuses_unproducible_demand():
    from brain_core.decompose import solve_decomposed
    f = _solvable_two_cell_factory()
    f.demands.append(Demand(name="GHOST", item="ZZZ",
                            due=H0 + timedelta(days=1), quantity=5.0))
    res = solve_decomposed(f, H0, days=2, cap_min=480.0,
                           bucket_time_s=5, seq_time_s=2)
    assert res.problems
    assert any("GHOST" in p for p in res.problems)
    assert res.plan.assignments == []
