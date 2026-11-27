"""Golden fixture: expected values written BY HAND from the record
spec, not produced by any code. The model helpers and the validator's
independent data must both equal these literals, so a shared
misreading of the schema (duplicate loads, sign of a material, what
"due at midnight" means) cannot hide in both.

Hand derivation (horizon start 2026-12-01 00:00):
 OP-A: product A, consumes 2.5 RM-1 per unit; 30 s per unit = 0.5 min
       => rate 2.0 units/min; loads L1, L2 and L1 again (a duplicate
       listing) => eligible lines {L1, L2}; setup state "s1" (first
       load that names one)
 OP-B: product B, no raw material; 60 s per unit => rate 1.0 units/min;
       load L2 => eligible {L2}; no setup state
 due-day rule: a due at midnight ENDING day d is day d.
   2026-12-02 00:00 -> end of Dec 1  -> day 0
   2026-12-03 12:00 -> inside Dec 3  -> day 2
   2026-12-01 00:00 -> end of Nov 30 -> day -1 (before the window)
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "packages" / "brain-core"))

from brain_core.guards.independent_data import (raw_due_day,  # noqa: E402
                                                raw_recipe_data,
                                                raw_sku_data)
from brain_core.records.models import (Demand, Factory, Item,  # noqa: E402
                                       Operation, OperationMaterial,
                                       OperationResource, Resource)
from brain_core.rolling import two_level as T  # noqa: E402
from brain_core.rolling.coupled import validate_coupled_plan  # noqa: E402

H0 = datetime(2026, 12, 1)


def _factory():
    return Factory(
        name="golden",
        items=[Item(name=n) for n in ("A", "B", "RM-1")],
        resources=[Resource(name="L1"), Resource(name="L2")],
        operations=[
            Operation(name="OP-A", item="A",
                      duration_per=timedelta(seconds=30),
                      materials=[OperationMaterial(item="A", quantity=1.0),
                                 OperationMaterial(item="RM-1",
                                                   quantity=-2.5)],
                      loads=[OperationResource(resource="L1", setup="s1"),
                             OperationResource(resource="L2"),
                             OperationResource(resource="L1", setup="s1")]),
            Operation(name="OP-B", item="B",
                      duration_per=timedelta(seconds=60),
                      materials=[OperationMaterial(item="B", quantity=1.0)],
                      loads=[OperationResource(resource="L2")]),
        ],
        demands=[Demand(name="d1", item="A", due=datetime(2026, 12, 2),
                        quantity=120.0)])


def test_model_helpers_match_hand_values():
    f = _factory()
    sku = T._sku_data(f)
    assert sku["A"][0] == 2.0 and sorted(sku["A"][1]) == ["L1", "L2"]
    assert sku["A"][2] == "s1"
    assert sku["B"][0] == 1.0 and sku["B"][1] == ["L2"]
    assert sku["B"][2] is None
    assert T._recipe_data(f) == {"A": {"RM-1": 2.5}}
    assert T.due_day(datetime(2026, 12, 2), H0) == 0
    assert T.due_day(datetime(2026, 12, 3, 12), H0) == 2
    assert T.due_day(datetime(2026, 12, 1), H0) == -1


def test_validator_data_matches_hand_values():
    f = _factory()
    sku = raw_sku_data(f)
    assert sku["A"] == (2.0, ["L1", "L2"], "s1")
    assert sku["B"] == (1.0, ["L2"], None)
    assert raw_recipe_data(f) == {"A": {"RM-1": 2.5}}
    assert raw_due_day(datetime(2026, 12, 2), H0) == 0
    assert raw_due_day(datetime(2026, 12, 3, 12), H0) == 2
    assert raw_due_day(datetime(2026, 12, 1), H0) == -1


def test_validator_on_hand_plan():
    """120 units of A on L1 day 0: 60 min (cap 480*(1-allowance) is far
    above), uses 300.0 RM-1, covers the 120 due day 0 exactly."""
    f = _factory()
    plan = {("A", 0, "L1"): 120.0}
    probs, k = validate_coupled_plan([f], [plan], H0, 3, 480.0,
                                     supplier_cap={("RM-1", 0): 300.0})
    assert probs == [], probs
    assert k["late_unit_days"] == 0 and k["backlog_units_end"] == 0
    # produced on day 0 for a day-0 due: nothing is early. A due-day
    # rule off by one (or a duplicated line counted twice in the stock
    # walk) makes this 120.0
    assert k["early_unit_days"] == 0
    probs, _ = validate_coupled_plan([f], [plan], H0, 3, 480.0,
                                     supplier_cap={("RM-1", 0): 299.0})
    assert any("supplier pool" in p for p in probs)
