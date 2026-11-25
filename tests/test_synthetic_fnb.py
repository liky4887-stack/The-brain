"""Stage 2 slice 1: synthetic F&B factory generator (gate scale).

The generator is the foundation for the rolling-horizon solve, the
ingestion pipeline and the back-test. Tests lock: determinism, the
published Makkook shape (17 lines / 96 slots / 4,001 SKUs), record
integrity, ground-truth feasibility checked independently, the
utilization band, and JSON round-trip.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.synthetic import (FnbParams, SyntheticPlant,
                                  generate_fnb_factory, verify_ground_truth)
from brain_core.synthetic.fnb_factory import (ALLERGEN_MIN, CROSS_CLASS_MIN,
                                              CROSS_FAMILY_MIN, FAMILIES,
                                              _build_setup_matrix)


@pytest.fixture(scope="module")
def plant():
    return generate_fnb_factory()


def test_gate_scale_shape(plant):
    f = plant.factory
    lines = [r for r in f.resources]
    assert len(lines) == 17
    skus = [i for i in f.items if i.name.startswith("SKU-")]
    assert len(skus) == 4001
    assert plant.params.slots_per_day == 96
    assert plant.day_capacity_minutes == 96 * 15
    assert all(r.setup_matrix == "CHG-STD" for r in lines)
    assert plant.factory.validate_references() == []


def test_determinism():
    a = generate_fnb_factory()
    b = generate_fnb_factory()
    assert a.factory.model_dump_json() == b.factory.model_dump_json()
    assert a.lots == b.lots
    c = generate_fnb_factory(FnbParams(seed=7))
    assert c.factory.model_dump_json() != a.factory.model_dump_json()


def test_ground_truth_feasible_independently(plant):
    # verify_ground_truth reads records + lots only, not generator state
    assert verify_ground_truth(plant) == []


def test_utilization_band(plant):
    cap = (plant.params.n_lines * plant.params.days
           * plant.day_capacity_minutes)
    prod_min = 0.0
    rate = {op.item: op.duration_per.total_seconds() / 60.0
            for op in plant.factory.operations}
    for lot in plant.lots:
        prod_min += lot.qty * rate[lot.sku]
    # scaling targets 0.70 production minutes; rounding keeps a band
    assert 0.60 <= prod_min / cap <= 0.72
    active = {lot.sku for lot in plant.lots}
    assert len(active) >= 0.15 * 4001  # long tail, but not degenerate


def test_demand_covered_by_ground_truth(plant):
    # every demand line is for an active SKU due inside the horizon
    horizon_end = plant.params.horizon_start + timedelta(days=plant.params.days)
    active = {lot.sku for lot in plant.lots}
    for d in plant.factory.demands:
        assert d.item in active
        assert plant.params.horizon_start < d.due <= horizon_end


def test_setup_matrix_rules():
    mtx = _build_setup_matrix()
    z = timedelta(0)
    assert mtx.duration_between("DAIRY-C0", "DAIRY-C0") == z
    assert mtx.duration_between("DAIRY-C1", "DAIRY-C2") == timedelta(minutes=CROSS_CLASS_MIN)
    assert mtx.duration_between("DAIRY-C1", "BAKERY-C1") == timedelta(minutes=CROSS_FAMILY_MIN)
    assert mtx.duration_between("BAKERY-C1", "DAIRY-C0") == timedelta(minutes=ALLERGEN_MIN)
    assert mtx.duration_between("SNACK-C3", "SAUCE-C1") == timedelta(minutes=ALLERGEN_MIN)
    # all states x states covered
    states = [f"{f}-C{c}" for f in FAMILIES for c in range(4)]
    for a in states:
        for b in states:
            assert mtx.duration_between(a, b) is not None


def test_tiny_plant_handcheck():
    p = generate_fnb_factory(FnbParams(seed=3, n_lines=2, n_skus=12, days=3,
                                       active_fraction=0.9, utilization=0.5,
                                       n_raw_materials=4,
                                       families=("DAIRY", "BAKERY")))
    f = p.factory
    assert f.validate_references() == []
    assert verify_ground_truth(p) == []
    # every operation has a positive self-material and 1-3 raw consumptions
    for op in f.operations:
        pos = [m for m in op.materials if m.quantity > 0]
        neg = [m for m in op.materials if m.quantity < 0]
        assert len(pos) == 1 and pos[0].item == op.item
        assert 1 <= len(neg) <= 3
        assert 1 <= len(op.loads) <= 2
        for ld in op.loads:
            assert ld.setup is not None


def test_json_roundtrip(tmp_path):
    a = generate_fnb_factory(FnbParams(seed=5, n_lines=3, n_skus=40, days=4,
                                       n_raw_materials=5,
                                       families=("DAIRY", "BAKERY", "SAUCE")))
    path = tmp_path / "plant.json"
    a.save(str(path))
    b = SyntheticPlant.load(str(path))
    assert a.factory.model_dump_json() == b.factory.model_dump_json()
    assert a.lots == b.lots
    assert a.params == b.params
