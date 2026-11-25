"""Tests for the compiler templates and solver router (Stage 1).

The lot-sizing template is validated against Wolsey Example 5.1 (locked
in lotsizing/) through the records boundary; the job-shop template
against a hand-computable bakery chain; the router's decisions checked
on structurally different factories. No test locks a CP-SAT solution's
exact values (nondeterministic with workers > 1) - only structure.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.compiler import compile_jobshop, compile_lotsizing, route
from brain_core.records import (
    Buffer, Demand, Factory, Item, Location, Operation, OperationMaterial,
    OperationResource, Resource,
)

D0 = datetime(2026, 11, 25)
DAY = timedelta(days=1)


def wolsey_factory() -> Factory:
    """Wolsey Example 5.1 as records: d = (5,7,11,9,6,9) over 6 days."""
    return Factory(
        locations=[Location(name="L")],
        items=[Item(name="Widget")],
        resources=[Resource(name="Line", location="L")],
        operations=[Operation(
            name="MakeWidget", item="Widget", location="L", cost=1.0,
            materials=[OperationMaterial(item="Widget", quantity=1.0)],
            loads=[OperationResource(resource="Line")])],
        buffers=[Buffer(item="Widget", location="L", onhand=0.0)],
        demands=[Demand(name=f"D{t}", item="Widget", location="L",
                        due=D0 + t * DAY, quantity=q)
                 for t, q in enumerate([5, 7, 11, 9, 6, 9])],
    )


def test_lotsizing_template_matches_wolsey_example_5_1():
    periods = [D0 + t * DAY for t in range(6)]
    c = compile_lotsizing(wolsey_factory(), "Widget", periods, DAY,
                          setup_cost=17.0, holding_cost=1.0)
    assert c.item == "Widget" and c.operation == "MakeWidget"
    assert c.demands == (5.0, 7.0, 11.0, 9.0, 6.0, 9.0)
    # verified by brute-force enumeration of all 2^6 setup sets at
    # authoring time (the book's own locked values live in uls.py's
    # tests; this lock covers the records->ULS boundary)
    assert c.total_cost == 123.0
    assert sum(o[1] for o in c.production_orders) == 47.0


def test_lotsizing_onhand_stock_covers_first_demands():
    f = wolsey_factory()
    f.buffers[0].onhand = 12.0  # covers periods 1-2 fully
    periods = [D0 + t * DAY for t in range(6)]
    c = compile_lotsizing(f, "Widget", periods, DAY,
                          setup_cost=17.0, holding_cost=1.0)
    assert c.demands[:2] == (0.0, 0.0)
    assert c.total_cost < 99.0


def test_lotsizing_rejects_out_of_horizon_and_multi_source():
    f = wolsey_factory()
    f.demands.append(Demand(name="Late", item="Widget",
                            due=D0 + 9 * DAY, quantity=3))
    periods = [D0 + t * DAY for t in range(6)]
    with pytest.raises(ValueError, match="outside horizon"):
        compile_lotsizing(f, "Widget", periods, DAY,
                          setup_cost=1.0, holding_cost=1.0)
    f2 = wolsey_factory()
    f2.operations.append(Operation(
        name="MakeWidget2", item="Widget",
        materials=[OperationMaterial(item="Widget", quantity=1.0)],
        loads=[OperationResource(resource="Line")]))
    with pytest.raises(ValueError, match="single-source"):
        compile_lotsizing(f2, "Widget", periods, DAY,
                          setup_cost=1.0, holding_cost=1.0)


def bakery_chain() -> Factory:
    """Flour -> Dough -> Bread: a two-step BOM chain."""
    return Factory(
        locations=[Location(name="Bakery")],
        items=[Item(name="Flour"), Item(name="Dough"), Item(name="Bread")],
        resources=[Resource(name="Mixer", location="Bakery"),
                   Resource(name="Oven", location="Bakery")],
        operations=[
            Operation(name="MixDough", item="Dough", location="Bakery",
                      duration=timedelta(minutes=20),
                      materials=[OperationMaterial(item="Flour", quantity=-1.0),
                                 OperationMaterial(item="Dough", quantity=1.0)],
                      loads=[OperationResource(resource="Mixer")]),
            Operation(name="BakeBread", item="Bread", location="Bakery",
                      duration=timedelta(minutes=10),
                      duration_per=timedelta(minutes=2),
                      materials=[OperationMaterial(item="Dough", quantity=-1.0),
                                 OperationMaterial(item="Bread", quantity=1.0)],
                      loads=[OperationResource(resource="Oven")]),
        ],
        demands=[Demand(name="Order-1", item="Bread", location="Bakery",
                        due=D0 + DAY, quantity=5.0)],
    )


def test_jobshop_template_bom_chain():
    c = compile_jobshop(bakery_chain())
    assert c.job_names == ("Order-1",)
    # route: MixDough 20 min on Mixer, then Bake 10 + 2*5 = 20 min on Oven
    assert c.instance.routes == ((("Mixer", 20), ("Oven", 20)),)
    assert c.step_sources == (("MixDough", "BakeBread"),)


def test_jobshop_template_skips_purchased_and_detects_cycles():
    f = bakery_chain()  # Flour is purchased: no step for it
    assert len(f.producing_operations("Flour")) == 0
    c = compile_jobshop(f)
    assert all("Flour" not in str(s) for s in c.step_sources)
    # cycle: Dough op consumes Bread
    f.operations[0].materials.append(
        OperationMaterial(item="Bread", quantity=-0.1))
    with pytest.raises(ValueError, match="BOM cycle"):
        compile_jobshop(f)


def test_router_decisions():
    assert route(wolsey_factory()).engine == "lotsizing-dp"
    decision = route(bakery_chain())
    assert decision.engine == "cpsat"
    assert any("disjunctive" in r for r in decision.reasons)
    empty = Factory(items=[Item(name="X")],
                    demands=[Demand(name="D", item="X", due=D0, quantity=1)])
    assert route(empty).engine == "highs"
