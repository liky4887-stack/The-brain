"""Stage 4, slice 7: tenant isolation is structural.

Crafted ids must be rejected before the filesystem is touched; two
tenants' factories, plans and audit logs are independent.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.records.models import (Demand, Factory, Item, Location)
from brain_core.tenancy import TenantError, TenantStore

H0 = datetime(2026, 11, 30)


def _factory(item="A"):
    return Factory(locations=[Location(name="P")],
                   items=[Item(name=item)],
                   demands=[Demand(name="D1", item=item,
                                   due=H0 + timedelta(days=1),
                                   quantity=10.0)])


def test_round_trip_factory_and_plan(tmp_path):
    store = TenantStore(tmp_path / "tenants")
    store.put_factory("acme", "main", _factory("A"))
    f = store.get_factory("acme", "main")
    assert f.items[0].name == "A"
    store.put_plan("acme", "w1", [{"line": "L1", "qty": 10.0}])
    assert store.get_plan("acme", "w1") == [{"line": "L1", "qty": 10.0}]
    assert store.list_tenants() == ["acme"]


def test_tenants_are_independent(tmp_path):
    store = TenantStore(tmp_path / "tenants")
    store.put_factory("acme", "main", _factory("A"))
    store.put_factory("globex", "main", _factory("B"))
    assert store.get_factory("acme", "main").items[0].name == "A"
    assert store.get_factory("globex", "main").items[0].name == "B"
    with pytest.raises(TenantError):
        store.get_factory("acme", "nope")
    # audit logs are separate files
    la = store.audit_log("acme")
    lb = store.audit_log("globex")
    assert la.path != lb.path
    assert la.entries() == [] and lb.entries() == []
    assert store.list_tenants() == ["acme", "globex"]


@pytest.mark.parametrize("bad", ["../globex", "a/../b", "/etc",
                                 "a b", "A", "a_b", "", "-x", "x-",
                                 "a/b", ".hidden"])
def test_crafted_tenant_ids_rejected(tmp_path, bad):
    store = TenantStore(tmp_path / "tenants")
    store.put_factory("globex", "main", _factory("B"))
    with pytest.raises(TenantError):
        store.get_factory(bad, "main")
    with pytest.raises(TenantError):
        store.put_factory(bad, "main", _factory())
    # nothing leaked or was created outside the root
    assert store.list_tenants() == ["globex"]


def test_object_names_validated_too(tmp_path):
    store = TenantStore(tmp_path / "tenants")
    store.put_factory("acme", "main", _factory())
    with pytest.raises(TenantError):
        store.get_factory("acme", "../globex/main")
