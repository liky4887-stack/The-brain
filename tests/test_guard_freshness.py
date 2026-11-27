from brain_core.guards.freshness import check_inputs, content_hash

SPEC = {"sku": str, "qty": float}


def good(**kw):
    d = {"sku": "A", "qty": 5.0, "as_of": 1000.0}
    d.update(kw)
    return d


def test_good_passes():
    assert check_inputs(good(), SPEC, now=1010.0, max_age_s=60) == []


def test_fault_injection_each_defect_caught():
    assert any("stale" in x for x in
               check_inputs(good(), SPEC, now=5000.0, max_age_s=60))
    assert any("missing field" in x for x in check_inputs(
        {"sku": "A", "as_of": 1000.0}, SPEC, now=1010.0, max_age_s=60))
    assert any("expected float" in x for x in check_inputs(
        good(qty="5"), SPEC, now=1010.0, max_age_s=60))
    assert any("unexpected" in x for x in check_inputs(
        good(color="red"), SPEC, now=1010.0, max_age_s=60))
    assert any("as_of missing" in x for x in check_inputs(
        {"sku": "A", "qty": 1.0}, SPEC, now=1.0, max_age_s=60))


def test_pinned_hash_detects_changed_content():
    h = content_hash({"sku": "A", "qty": 5.0})
    assert check_inputs(good(), SPEC, 1010.0, 60, pinned_hash=h) == []
    assert any("hash" in x for x in check_inputs(
        good(qty=6.0), SPEC, 1010.0, 60, pinned_hash=h))
