"""Solver router: pick the engine from the problem's structure (Stage 1).

Rules (from the books and the CP-SAT Primer, applied honestly):

- Single item, single production source, demands over discrete
  periods, no resource contention modeled -> "lotsizing-dp": the
  Wagner-Whitin DP is EXACT for ULS, no black-box solver needed.
- Multiple jobs sharing machines, or BOM chains -> "cpsat": disjunctive
  structure is CP-SAT's crown jewel (Primer: no_overlap).
- Pure continuous linear problems -> "highs" (LP): CP-SAT is not an LP
  solver. No current template emits pure LP, so the router documents
  the rule and flags when it would apply; it never routes a problem to
  an engine that has no model for it.

The router returns a decision WITH reasons so the plan can explain
itself (Stage 3 audit trail).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..records.models import Factory


@dataclass(frozen=True)
class RouteDecision:
    engine: str            # "lotsizing-dp" | "cpsat" | "highs" (see module doc)
    reasons: tuple


def route(factory: Factory) -> RouteDecision:
    reasons = []
    produced_items = {m.item for op in factory.operations
                      for m in op.materials if m.quantity > 0}
    scheduled = [d for d in factory.demands if d.item in produced_items]
    if not factory.operations:
        return RouteDecision("highs", (
            "no operations: nothing to schedule; purchasing/inventory "
            "balance is a pure linear problem for HiGHS",))
    if not scheduled:
        reasons.append("no demand for in-factory items: nothing to schedule")
        return RouteDecision("highs", tuple(reasons))
    resources_used = {ld.resource for op in factory.operations for ld in op.loads}
    multi_step = any(
        any(m.quantity < 0 and m.item in produced_items for m in op.materials)
        for op in factory.operations)
    single_source = all(
        len(factory.producing_operations(it)) == 1 for it in produced_items)
    if (len(resources_used) == 1 and single_source and not multi_step
            and len(produced_items) == 1):
        reasons.append("single item, single source, single resource, "
                       "discrete periods: ULS structure")
        reasons.append("Wagner-Whitin DP is exact for ULS (Wolsey 5.2): "
                       "no solver needed")
        return RouteDecision("lotsizing-dp", tuple(reasons))
    if resources_used:
        reasons.append(f"{len(resources_used)} resource(s) shared by jobs or "
                       "multi-step BOM: disjunctive structure")
        reasons.append("disjunctive scheduling is CP-SAT's strongest ground "
                       "(CP-SAT Primer: no_overlap)")
        return RouteDecision("cpsat", tuple(reasons))
    return RouteDecision("highs", ("no resource loads: linear balance only",))
