"""Stage 2, slice 4: cockpit data API.

Plan payload and KPIs recomputed from records (never solver echoes),
late-order explanations as computed facts, the JSON server endpoints,
and the zero-dependency SVG Gantt.
"""

import json
import sys
import threading
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.cockpit import (late_order_report, make_server,
                                plan_to_dict, render_gantt_html)
from brain_core.records.models import (Demand, Factory, Item, Location,
                                       Operation, OperationMaterial,
                                       OperationResource, Resource,
                                       SetupMatrix, SetupRule)
from brain_core.rolling import solve_window
from brain_core.rolling.two_level import WindowPlan
from brain_core.synthetic import FnbParams, generate_fnb_factory

H0 = datetime(2026, 11, 30)  # Monday


def tiny_factory(qty=100.0, due_day_idx=0):
    f = Factory(
        locations=[Location(name="P")],
        items=[Item(name="A"), Item(name="B")],
        setup_matrices=[SetupMatrix(name="CHG", rules=[
            SetupRule(from_setup="S1", to_setup="S2",
                      duration=timedelta(minutes=30)),
            SetupRule(from_setup="S2", to_setup="S1",
                      duration=timedelta(minutes=30))])],
        resources=[Resource(name="L1", location="P", setup_matrix="CHG")],
        operations=[
            Operation(name="MAKE-A", item="A", location="P",
                      duration_per=timedelta(minutes=1),
                      materials=[OperationMaterial(item="A", quantity=1)],
                      loads=[OperationResource(resource="L1", setup="S1")]),
            Operation(name="MAKE-B", item="B", location="P",
                      duration_per=timedelta(minutes=1),
                      materials=[OperationMaterial(item="B", quantity=1)],
                      loads=[OperationResource(resource="L1", setup="S2")]),
        ],
        demands=[Demand(name="D1", item="A", location="P",
                        due=H0 + timedelta(days=due_day_idx + 1),
                        quantity=qty)])
    return f


def test_plan_payload_recomputed_and_loads_within_capacity():
    f = tiny_factory(qty=100.0)
    # real solve of the tiny plant: 100 min production on day 0
    plan = solve_window(f, H0, 1, 480.0, bucket_time_s=10, seq_time_s=5)
    assert plan.problems == []
    payload = plan_to_dict(f, plan, 480.0)
    assert payload["kpis"]["backlog_units_end"] == pytest.approx(0.0)
    assert payload["kpis"]["assignments"] >= 1
    for line, days in payload["line_day_load_minutes"].items():
        for day, load in days.items():
            assert load <= 480.0 + 0.05
    assert payload["assignments"][0]["sku"] == "A"
    assert payload["bucket_objective"] is not None


def test_late_order_report_states_computed_facts():
    f = tiny_factory(qty=100.0)
    plan = WindowPlan(H0, 1, [], None, "test")  # nothing produced
    report = late_order_report(f, plan, 480.0)
    assert report["total_late_skus"] == 1
    [late] = report["late_skus"]
    assert late["sku"] == "A"
    assert late["day"] == 0
    assert late["shortfall_units"] == pytest.approx(100.0)
    assert [d["name"] for d in late["demands"]] == ["D1"]
    assert report["backlog_units_end"] == pytest.approx(100.0)


def test_gantt_html_renders_lines_skus_and_changeovers():
    f = tiny_factory(qty=60.0)
    # both SKUs on day 0: forces a 30-minute changeover on L1
    f.demands.append(Demand(name="D2", item="B", location="P",
                            due=H0 + timedelta(days=1), quantity=60.0))
    plan = solve_window(f, H0, 1, 480.0, bucket_time_s=10, seq_time_s=5)
    assert plan.problems == []
    html = render_gantt_html(f, plan, 480.0)
    assert "L1 day 0" in html
    assert "changeover 30 min" in html
    assert "MAKE" not in html  # shows SKUs, not operation names
    assert "A: 60" in html and "B: 60" in html


def test_server_endpoints():
    f = tiny_factory(qty=50.0)
    plan = solve_window(f, H0, 1, 480.0, bucket_time_s=10, seq_time_s=5)
    server = make_server(f, plan, 480.0, port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def get(path):
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{path}") as resp:
                return resp.status, resp.read().decode()
        status, body = get("/api/health")
        assert status == 200 and json.loads(body)["status"] == "ok"
        status, body = get("/api/plan")
        payload = json.loads(body)
        assert status == 200
        assert payload["assignments"][0]["sku"] == "A"
        assert "kpis" in payload and "problems" in payload
        status, body = get("/api/kpis")
        assert json.loads(body)["backlog_units_end"] == 0.0
        status, body = get("/api/late-orders")
        assert json.loads(body)["total_late_skus"] == 0
        status, body = get("/gantt")
        assert status == 200 and "<svg" in body and "L1 day 0" in body
        with pytest.raises(Exception):
            get("/nope")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_gate_scale_payload_builds_fast():
    """The API layer must not become the bottleneck at Makkook size."""
    import time
    p = generate_fnb_factory(FnbParams(seed=5, n_lines=3, n_skus=40,
                                       days=2, n_raw_materials=5,
                                       families=("DAIRY", "BAKERY",
                                                 "SAUCE")))
    plan = solve_window(p.factory, p.params.horizon_start, p.params.days,
                        p.day_capacity_minutes, bucket_time_s=20,
                        seq_time_s=5)
    assert plan.problems == []
    t0 = time.time()
    payload = plan_to_dict(p.factory, plan, p.day_capacity_minutes)
    html = render_gantt_html(p.factory, plan, p.day_capacity_minutes)
    assert time.time() - t0 < 5.0
    assert payload["assignments"]
    assert "<svg" in html
