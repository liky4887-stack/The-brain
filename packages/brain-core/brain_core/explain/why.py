"""Plain-words explanations of plans (Stage 3, slice 5).

Every sentence is a measured fact recomputed from the records and the
returned plan - the same arithmetic as the independent validator,
never the solver's word and never an inference. No LLM writes these
(decisions: LLMs never decide plans); a template fills in measured
numbers.

What it answers:
- which line-days are binding (full): the reason nothing more fits;
- why a SKU is late: demand due vs produced by its due day, plus the
  measured state of the line-days that could have run it;
- why a window is infeasible before solving: required production
  minutes vs available line minutes, per line and in total.
"""

from __future__ import annotations

from ..records.models import Factory
from ..rolling.two_level import (WindowPlan, _sku_data, due_day,
                                 matrices_duration)

FULL_TOL_MIN = 0.05     # same tolerance the validator uses


def _line_day_usage(factory: Factory, plan: WindowPlan, day0: int = 0
                    ) -> dict[tuple[str, int], dict]:
    """(line, day) -> measured usage: production/changeover/total
    minutes and changeover count, from the returned sequence."""
    sku = _sku_data(factory)
    matrices = {m.name: m for m in factory.setup_matrices}
    res_mtx = {r.name: matrices.get(r.setup_matrix)
               for r in factory.resources}
    by_ld: dict[tuple[str, int], list] = {}
    for a in plan.assignments:
        by_ld.setdefault((a.line, a.day - day0), []).append(a)
    usage = {}
    for (line, day), lots in by_ld.items():
        lots = sorted(lots, key=lambda a: a.seq_pos)
        mtx = res_mtx.get(line)
        prod = chg = 0.0
        n_chg = 0
        prev = None
        for a in lots:
            if a.sku not in sku:
                continue
            rate, _, state = sku[a.sku]
            prod += a.qty / rate
            if prev is not None and mtx is not None:
                d = matrices_duration(mtx, prev, state)
                chg += d
                n_chg += 1
            prev = state
        usage[(line, day)] = {"production_min": prod,
                              "changeover_min": chg,
                              "changeovers": n_chg,
                              "total_min": prod + chg}
    return usage


def binding_line_days(factory: Factory, plan: WindowPlan,
                      cap_min: float, day0: int = 0) -> list[str]:
    """Plain-words list of FULL line-days (the binding constraints),
    busiest first. A line-day is binding when its measured use is
    within FULL_TOL_MIN of capacity - the same threshold the
    validator uses to call a violation."""
    usage = _line_day_usage(factory, plan, day0)
    rows = [(u["total_min"], line, day, u)
            for (line, day), u in usage.items()
            if u["total_min"] >= cap_min - FULL_TOL_MIN]
    rows.sort(reverse=True)
    return [f"{line} day {day} is FULL: {u['total_min']:.0f} of "
            f"{cap_min:.0f} minutes used "
            f"({u['production_min']:.0f} production + "
            f"{u['changeover_min']:.0f} changeover in "
            f"{u['changeovers']} changeovers)"
            for _, line, day, u in rows]


def explain_late(factory: Factory, plan: WindowPlan,
                 cap_min: float) -> list[str]:
    """Per late SKU, the measured facts: how much was due by when,
    how much the plan produced by then, and how full the eligible
    line-days before the due day were."""
    sku = _sku_data(factory)
    usage = _line_day_usage(factory, plan)
    produced_by: dict[tuple[str, int], float] = {}
    for a in plan.assignments:
        produced_by[(a.sku, a.day)] = (produced_by.get((a.sku, a.day), 0.0)
                                       + a.qty)
    out = []
    demands = sorted(factory.demands, key=lambda d: (d.due, d.item))
    for d in demands:
        dd = due_day(d.due, plan.horizon_start)
        made = sum(q for (s, day), q in produced_by.items()
                   if s == d.item and day <= dd)
        if made >= d.quantity - 1e-9:
            continue
        short = d.quantity - made
        lines = sku.get(d.item, (None, [], None))[1]
        eligible = [(line, day) for line in lines
                    for day in range(dd + 1)]
        used = sum(usage.get(ld, {"total_min": 0.0})["total_min"]
                   for ld in eligible)
        avail = cap_min * len(eligible)
        pct = (100.0 * used / avail) if avail else 0.0
        out.append(
            f"{d.item}: {d.quantity:.0f} units due day {dd} "
            f"({d.name}); the plan makes {made:.0f} by then - "
            f"{short:.0f} late. Its eligible lines "
            f"({', '.join(lines) if lines else 'none recorded'}) ran "
            f"at {pct:.0f}% of minutes on days 0..{dd} "
            f"({used:.0f} of {avail:.0f} min incl. changeovers).")
    return out


def explain_infeasible(factory: Factory, horizon_start, days: int,
                       cap_min: float) -> list[str]:
    """Measured aggregate capacity facts when a window cannot fit the
    demand due inside it. Necessary-condition arithmetic only: it can
    prove overload, it cannot prove feasibility."""
    sku = _sku_data(factory)
    need: dict[str, float] = {}     # sku -> production minutes due
    for d in factory.demands:
        dd = due_day(d.due, horizon_start)
        if 0 <= dd < days and d.item in sku:
            rate = sku[d.item][0]
            need[d.item] = need.get(d.item, 0.0) + d.quantity / rate
    total_need = sum(need.values())
    cap_total = cap_min * days * len(factory.resources)
    out = [f"demand due in the window needs {total_need:.0f} "
           f"production minutes; {len(factory.resources)} lines x "
           f"{days} days offer {cap_total:.0f} minutes before any "
           f"changeover"]
    if total_need > cap_total:
        out.append(f"INFEASIBLE in aggregate: need exceeds capacity "
                   f"by {total_need - cap_total:.0f} minutes "
                   f"({100 * total_need / cap_total - 100:.0f}% over)")
    per_line: dict[str, float] = {}
    for s, minutes in need.items():
        lines = sku[s][1]
        for line in lines:
            per_line[line] = per_line.get(line, 0.0)
        # attribute fully when only one line is eligible
        if len(lines) == 1:
            per_line[lines[0]] += minutes
    for line, minutes in sorted(per_line.items(),
                                key=lambda kv: -kv[1]):
        cap = cap_min * days
        if minutes > cap:
            out.append(f"{line}: {minutes:.0f} minutes of demand can "
                       f"ONLY run here but it offers {cap:.0f} - "
                       f"{minutes - cap:.0f} minutes over")
    return out


def explain_plan(factory: Factory, plan: WindowPlan,
                 cap_min: float) -> list[str]:
    """The full factual picture: binding line-days then lateness."""
    return (binding_line_days(factory, plan, cap_min)
            + explain_late(factory, plan, cap_min))
