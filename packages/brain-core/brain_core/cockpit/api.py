"""Planner cockpit data API (Stage 2, slice 4).

The data layer behind the planner cockpit: a WindowPlan plus the
Factory records, served as JSON over a stdlib http.server, plus one
zero-dependency HTML/SVG Gantt page so a planner can read the plan in
a browser today.

Design rules honored here:
- stdlib only (http.server, json); no web framework enters the tree
  without the decision-4 license check, and none is needed here.
- Next.js + vis-timeline cockpit is DEFERRED (DECISIONS.md): the API
  is the contract any future UI consumes; the SVG Gantt proves the
  data is sufficient for a planner-readable view.
- Every number served is recomputed from records + returned
  assignments by the same independent-validator logic; solver
  internals are never re-exposed as fact.
- Explanations state computed facts only (shortfall, day loads,
  changeovers); no speculation about causes the data does not show.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..records.models import Factory
from ..rolling.two_level import (LotAssignment, WindowPlan, due_day,
                                 validate_window_plan)


def plan_to_dict(factory: Factory, plan: WindowPlan,
                 cap_min: float) -> dict:
    """The full plan payload: assignments, KPIs, problems, per-line-day
    loads. All numbers recomputed by the independent validator."""
    v_problems, kpis = validate_window_plan(factory, plan, cap_min)
    loads: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    matrices = {m.name: m for m in factory.setup_matrices}
    res_mtx = {r.name: matrices.get(r.setup_matrix)
               for r in factory.resources}
    by_ld: dict[tuple[str, int], list[LotAssignment]] = defaultdict(list)
    for a in plan.assignments:
        by_ld[(a.line, a.day)].append(a)
    for (line, day), lots in by_ld.items():
        lots.sort(key=lambda a: a.seq_pos)
        total = 0.0
        prev = None
        for a in lots:
            rate = _rate(factory, a.sku)
            total += a.qty / rate if rate else 0.0
            state = _state_of(factory, a.sku)
            if prev is not None and state is not None:
                mtx = res_mtx.get(line)
                d = mtx.duration_between(prev, state) if mtx else None
                total += d.total_seconds() / 60.0 if d else 0.0
            prev = state
        loads[line][str(day)] = round(total, 3)
    return {
        "horizon_start": plan.horizon_start.isoformat(),
        "days": plan.days,
        "status": plan.seq_status,
        "bucket_objective": plan.bucket.objective if plan.bucket else None,
        "bucket_status": plan.bucket.status if plan.bucket else None,
        "assignments": [
            {"line": a.line, "day": a.day, "seq_pos": a.seq_pos,
             "sku": a.sku, "qty": a.qty,
             "changeover_from_prev_min": a.chg_from_prev_min}
            for a in sorted(plan.assignments,
                            key=lambda a: (a.day, a.line, a.seq_pos))],
        "line_day_load_minutes": {l: dict(days) for l, days in
                                  sorted(loads.items())},
        "capacity_minutes_per_line_day": cap_min,
        "kpis": kpis,
        "problems": sorted(set(plan.problems) | set(v_problems)),
    }


def late_order_report(factory: Factory, plan: WindowPlan,
                      cap_min: float) -> dict:
    """Per-SKU lateness with the computed facts a planner asks for.

    A SKU is late on day t when its cumulative stock (starting
    inventory + production - demand) goes negative at the end of day
    t. For each late (sku, day): the shortfall, the demands behind it,
    and that day's line loads as a fact (a loaded line-day is
    evidence, not a verdict).
    """
    rates = {o.item: o for o in factory.operations if o.item}
    dem: dict[str, list[float]] = {}
    dem_orders: dict[str, list[dict]] = defaultdict(list)
    for d in factory.demands:
        day = due_day(d.due, plan.horizon_start)
        if 0 <= day < plan.days:
            dem.setdefault(d.item, [0.0] * plan.days)[day] += d.quantity
            dem_orders[d.item].append(
                {"name": d.name, "due": d.due.isoformat(),
                 "quantity": d.quantity, "day": day})
    prod: dict[str, list[float]] = {}
    for a in plan.assignments:
        if 0 <= a.day < plan.days:
            prod.setdefault(a.sku, [0.0] * plan.days)[a.day] += a.qty
    payload = plan_to_dict(factory, plan, cap_min)
    loads = payload["line_day_load_minutes"]
    late = []
    for sku in sorted(set(dem)):
        stock = 0.0
        p = prod.get(sku, [0.0] * plan.days)
        for t in range(plan.days):
            stock += p[t] - dem[sku][t]
            if stock < -1e-9:
                day_loads = {l: days[str(t)] for l, days in loads.items()
                             if str(t) in days}
                late.append({
                    "sku": sku, "day": t, "shortfall_units": -stock,
                    "demands": [o for o in dem_orders[sku]
                                if o["day"] <= t],
                    "fact_line_loads_that_day": day_loads,
                    "fact_capacity_per_line_day": cap_min,
                })
                break  # first late day per SKU; planner drills from there
    return {"late_skus": late,
            "total_late_skus": len(late),
            "backlog_units_end": payload["kpis"]["backlog_units_end"]}


def _rate(factory: Factory, sku: str) -> float | None:
    for o in factory.operations:
        if o.item == sku and o.duration_per.total_seconds() > 0:
            return 60.0 / (o.duration_per.total_seconds())
    return None


def _state_of(factory: Factory, sku: str) -> str | None:
    for o in factory.operations:
        if o.item == sku and o.loads:
            return o.loads[0].setup
    return None


_PALETTE = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2",
            "#eeca3b", "#b279a2", "#ff9da6", "#9d755d", "#bab0ac"]


def render_gantt_html(factory: Factory, plan: WindowPlan,
                      cap_min: float) -> str:
    """Self-contained HTML page: one SVG row per (line, day), bars
    placed by computed start minute within the day."""
    matrices = {m.name: m for m in factory.setup_matrices}
    res_mtx = {r.name: matrices.get(r.setup_matrix)
               for r in factory.resources}
    by_ld: dict[tuple[str, int], list[LotAssignment]] = defaultdict(list)
    for a in plan.assignments:
        by_ld[(a.line, a.day)].append(a)
    families = {a.sku: (_state_of(factory, a.sku) or "?").split("-")[0]
                for a in plan.assignments}
    fam_list = sorted(set(families.values()))
    color = {f: _PALETTE[i % len(_PALETTE)]
             for i, f in enumerate(fam_list)}
    scale = 900.0 / max(cap_min, 1.0)
    rows = []
    for (line, day) in sorted(by_ld, key=lambda k: (k[1], k[0])):
        lots = sorted(by_ld[(line, day)], key=lambda a: a.seq_pos)
        y = len(rows) * 22
        bars = []
        x = 0.0
        prev = None
        for a in lots:
            state = _state_of(factory, a.sku)
            if prev is not None and state is not None:
                mtx = res_mtx.get(line)
                d = mtx.duration_between(prev, state) if mtx else None
                chg = d.total_seconds() / 60.0 if d else 0.0
                if chg > 0:
                    bars.append(
                        f'<rect x="{x*scale:.1f}" y="{y+8}" '
                        f'width="{chg*scale:.1f}" height="10" '
                        f'fill="#333"><title>changeover {chg:.0f} min</title>'
                        f'</rect>')
                x += chg
            rate = _rate(factory, a.sku) or 1.0
            w = a.qty / rate
            fam = families[a.sku]
            bars.append(
                f'<rect x="{x*scale:.1f}" y="{y+4}" '
                f'width="{max(w*scale, 1.0):.1f}" height="18" '
                f'fill="{color[fam]}"><title>{a.sku}: {a.qty:.0f} units, '
                f'{w:.0f} min</title></rect>')
            x += w
            prev = state
        rows.append(
            f'<text x="0" y="{y+18}" font-size="11">{line} day {day}</text>'
            + "".join(bars))
    height = len(rows) * 22 + 60
    legend = "".join(
        f'<rect x="{10+i*110}" y="{height-40}" width="12" height="12" '
        f'fill="{color[f]}"/><text x="{26+i*110}" y="{height-30}" '
        f'font-size="11">{f}</text>'
        for i, f in enumerate(fam_list))
    kpi = plan.kpis
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>The-brain plan cockpit</title></head><body>"
        "<h2>Plan cockpit</h2>"
        f"<p>changeover minutes: {kpi.get('changeover_minutes', 0):.0f} "
        f"| setups: {kpi.get('setups', 0)} "
        f"| backlog units end: {kpi.get('backlog_units_end', 0):.0f} "
        f"| problems: {len(plan.problems)}</p>"
        f"<svg width='1100' height='{height}' "
        "xmlns='http://www.w3.org/2000/svg'>"
        + "".join(rows) + legend + "</svg></body></html>")


def make_server(factory: Factory, plan: WindowPlan, cap_min: float,
                host: str = "127.0.0.1", port: int = 8080
                ) -> ThreadingHTTPServer:
    """A read-only JSON cockpit server. Bind port 0 for tests."""
    payload = plan_to_dict(factory, plan, cap_min)
    late = late_order_report(factory, plan, cap_min)
    gantt = render_gantt_html(factory, plan, cap_min)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 (stdlib naming)
            if self.path == "/api/health":
                self._send(200, json.dumps({"status": "ok"}))
            elif self.path == "/api/plan":
                self._send(200, json.dumps(payload, default=str))
            elif self.path == "/api/kpis":
                self._send(200, json.dumps(payload["kpis"], default=str))
            elif self.path == "/api/late-orders":
                self._send(200, json.dumps(late, default=str))
            elif self.path == "/gantt":
                self._send(200, gantt, "text/html; charset=utf-8")
            else:
                self._send(404, json.dumps({"error": "not found"}))

        def log_message(self, *args):  # keep test output clean
            pass

    return ThreadingHTTPServer((host, port), Handler)
