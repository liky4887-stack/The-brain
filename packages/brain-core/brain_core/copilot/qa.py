"""Planner Q&A over solver output (Stage 4, slice 4).

The copilot contract (DECISIONS: LLMs never decide): every answer's
NUMBERS come from the records, the returned plan, the independent
validator, the explanations module, or the simulation twin - the same
measured arithmetic as everywhere else. An LLM front-end may phrase
these answers; it may not compute them. Each answer carries its
evidence so a planner can check it.

Unknown questions are refused honestly instead of guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..explain import binding_line_days, explain_late
from ..records.models import Factory
from ..rolling.two_level import WindowPlan, validate_window_plan
from ..simtwin import Disruption, execute


@dataclass
class Answer:
    question: str
    intent: str
    text: str
    evidence: dict = field(default_factory=dict)


def _fmt_units(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def answer(question: str, factory: Factory, plan: WindowPlan,
           cap_min: float) -> Answer:
    """Answer one planner question from measured facts.

    Intents: why_late, full_lines, changeovers, when_produced,
    how_late, proxy_cost, what_if_down, lots_on_day. Anything else:
    an honest refusal with the list of answerable intents.
    """
    q = question.strip().lower()          # intent detection
    orig = question.strip()               # entity extraction (SKUs,
                                          # demands, lines are
                                          # case-sensitive records)

    m = re.search(r"why is (\S+) late", orig, re.IGNORECASE)
    if m:
        sku = m.group(1).rstrip("?")
        lines = [s for s in explain_late(factory, plan, cap_min)
                 if s.startswith(sku + ":")]
        if not lines:
            return Answer(question, "why_late",
                          f"{sku} is not late in this plan.",
                          {"sku": sku, "late": False})
        return Answer(question, "why_late", lines[0],
                      {"sku": sku, "late": True})

    if "full" in q and ("line" in q or "day" in q):
        full = binding_line_days(factory, plan, cap_min)
        if not full:
            return Answer(question, "full_lines",
                          "No line-day is full.", {"full": []})
        return Answer(question, "full_lines",
                      f"{len(full)} line-days are full. "
                      + " ".join(full[:5]),
                      {"full": full})

    if "changeover" in q:
        problems, kpis = validate_window_plan(factory, plan, cap_min)
        chg = kpis["changeover_minutes"]
        return Answer(question, "changeovers",
                      f"The plan uses {_fmt_units(chg)} changeover "
                      f"minutes across {kpis['setups']} setups.",
                      {"changeover_minutes": chg,
                       "setups": kpis["setups"]})

    m = re.search(r"when is (?:demand |order )?(\S+) produced",
                  orig, re.IGNORECASE)
    if m:
        name = m.group(1).rstrip("?")
        dem = next((d for d in factory.demands if d.name == name),
                   None)
        if dem is None:
            return Answer(question, "when_produced",
                          f"No demand named {name}.",
                          {"found": False})
        lots = sorted((a.day, a.line, a.qty)
                      for a in plan.assignments
                      if a.sku == dem.item and a.qty > 1e-9)
        if not lots:
            return Answer(question, "when_produced",
                          f"{dem.item} (for {name}) is not produced "
                          f"in this window.",
                          {"found": True, "lots": []})
        text = "; ".join(f"day {d} on {l}: {_fmt_units(x)} units"
                         for d, l, x in lots)
        return Answer(question, "when_produced",
                      f"{dem.item} for {name}: {text}.",
                      {"found": True,
                       "lots": [{"day": d, "line": l, "qty": x}
                                for d, l, x in lots]})

    m = re.search(r"how (?:many units of |much of )?(\S+) (?:is|are) "
                  r"late", orig, re.IGNORECASE) \
        or re.search(r"how late is (\S+)", orig, re.IGNORECASE)
    if m:
        sku = m.group(1).rstrip("?")
        lines = [s for s in explain_late(factory, plan, cap_min)
                 if s.startswith(sku + ":")]
        if not lines:
            return Answer(question, "how_late",
                          f"{sku}: nothing late.",
                          {"sku": sku, "late_units": 0.0})
        mm = re.search(r"(\d+(?:\.\d+)?) late", lines[0])
        late = float(mm.group(1)) if mm else None
        return Answer(question, "how_late", lines[0],
                      {"sku": sku, "late_units": late})

    if "cost" in q or "objective" in q:
        _, kpis = validate_window_plan(factory, plan, cap_min)
        return Answer(question, "proxy_cost",
                      f"Proxy cost {_fmt_units(kpis['proxy_cost'])} "
                      f"(setups {kpis['setups']}, lateness "
                      f"{_fmt_units(kpis['backlog_unit_days'])} "
                      f"unit-days, earliness "
                      f"{_fmt_units(kpis['early_unit_days'])} "
                      f"unit-days).",
                      dict(kpis))

    m = re.search(r"(?:what if|if) (\S+) (?:is |goes )?down "
                  r"(?:on )?day (\d+)", orig, re.IGNORECASE)
    if m:
        line, day = m.group(1), int(m.group(2))
        out = execute(factory, plan, Disruption(down=((line, day),)))
        _, kpis = validate_window_plan(factory, plan, cap_min)
        delta = (out["backlog_units_end"]
                 - kpis["backlog_units_end"])
        return Answer(question, "what_if_down",
                      f"If {line} is down on day {day}: "
                      f"{_fmt_units(out['backlog_units_end'])} units "
                      f"late at horizon end "
                      f"({_fmt_units(delta)} more than the "
                      f"undisrupted plan), with no re-planning.",
                      {"line": line, "day": day,
                       "late_units_end": out["backlog_units_end"],
                       "delta_late_units": delta})

    m = re.search(r"how many lots on (\S+) day (\d+)", orig,
                  re.IGNORECASE)
    if m:
        line, day = m.group(1), int(m.group(2))
        lots = [a for a in plan.assignments
                if a.line == line and a.day == day and a.qty > 1e-9]
        total = sum(a.qty for a in lots)
        return Answer(question, "lots_on_day",
                      f"{len(lots)} lots on {line} day {day}, "
                      f"totaling {_fmt_units(total)} units.",
                      {"line": line, "day": day, "lots": len(lots),
                       "total_units": total})

    return Answer(question, "unknown",
                  "I can answer: why a SKU is late; which line-days "
                  "are full; changeover time; when a demand is "
                  "produced; how much of a SKU is late; proxy cost; "
                  "what if a line goes down on a day; how many lots "
                  "on a line-day.",
                  {"refused": True})
