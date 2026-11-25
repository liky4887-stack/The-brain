"""Parallel cell solve + merge (Stage 4, slice 1, second half).

partition_plants PROVES which cells are independent; this solves them
concurrently (stdlib ProcessPoolExecutor - no Ray/mpi-sppy dependency
yet, decision 4) and concatenates the assignments. Day indices are
absolute from the shared horizon_start, so the merge is a plain list
concatenation; the merged plan is then checked by the SAME independent
validator on the FULL factory, exactly like a monolithic plan.

If the partition reports problems (e.g. a demand no operation can
serve) the decomposed path refuses and reports - it never plans
around a record it could not place.
"""

from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

from ..records.models import Factory
from ..rolling.two_level import (WindowPlan, solve_window,
                                 validate_window_plan)
from .plants import partition_plants, sub_factory


@dataclass
class DecomposedResult:
    plan: WindowPlan
    cells: int
    wall_s: float                  # measured end-to-end
    max_cell_wall_s: float         # the bound parallelism exploits
    sum_cell_wall_s: float = 0.0   # sequential-solve lower bound
    problems: list[str] = field(default_factory=list)
    kpis: dict = field(default_factory=dict)
    decomposed: bool = True


def _solve_cell(args):
    factory, cell, horizon_start, days, cap_min, kw = args
    t0 = time.monotonic()
    plan = solve_window(sub_factory(factory, cell), horizon_start,
                        days, cap_min, **kw)
    return plan, time.monotonic() - t0


def solve_decomposed(factory: Factory, horizon_start, days: int,
                     cap_min: float, max_workers: int | None = None,
                     **solve_kw) -> DecomposedResult:
    """Partition -> solve cells in parallel -> merge -> validate on
    the full factory. Falls back to one cell (still correct, just
    not split) when the factory is fully coupled."""
    t0 = time.monotonic()
    part = partition_plants(factory)
    if part.problems:
        return DecomposedResult(
            plan=WindowPlan(horizon_start, days, [], None,
                            "not attempted"),
            cells=len(part.cells), wall_s=time.monotonic() - t0,
            max_cell_wall_s=0.0,
            problems=[f"partition refused: {p}"
                      for p in part.problems])
    jobs = [(factory, c, horizon_start, days, cap_min, solve_kw)
            for c in part.cells]
    if len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            solved = list(pool.map(_solve_cell, jobs))
    else:
        solved = [_solve_cell(j) for j in jobs]
    assignments = [a for plan, _ in solved for a in plan.assignments]
    cell_problems = [p for plan, _ in solved for p in plan.problems]
    max_cell = max((w for _, w in solved), default=0.0)
    sum_cell = sum(w for _, w in solved)
    # Merge the cells' bucket results: their qty dicts are disjoint by
    # construction (a SKU lives in exactly one cell), and the total
    # bucket objective is the sum of the per-cell recomputed
    # objectives. A cell whose bucket failed keeps the failure visible:
    # the merged objective is None then, and consumers (rolling) treat
    # the window as failed - nothing is hidden.
    from ..rolling.two_level import BucketResult
    cell_buckets = [plan.bucket for plan, _ in solved]
    if all(b is not None and b.objective is not None
           for b in cell_buckets):
        qty = {}
        for b in cell_buckets:
            qty.update(b.qty)
        merged_bucket = BucketResult(
            "merged-cells", sum(b.objective for b in cell_buckets),
            None, qty,
            sum(b.skipped_future_demands for b in cell_buckets),
            sum(b.n_binaries for b in cell_buckets),
            sum(b.n_vars for b in cell_buckets),
            sum(b.n_rows for b in cell_buckets))
    else:
        merged_bucket = BucketResult(
            "merged-cells:cell-failed", None, None, {},
            sum(b.skipped_future_demands for b in cell_buckets if b),
            0, 0)
    merged = WindowPlan(horizon_start, days, assignments, merged_bucket,
                        "merged:" + ",".join(p.seq_status
                                             for p, _ in solved),
                        problems=cell_problems)
    problems, kpis = validate_window_plan(factory, merged, cap_min)
    merged.problems = cell_problems + problems
    return DecomposedResult(
        plan=merged, cells=len(part.cells),
        wall_s=time.monotonic() - t0, max_cell_wall_s=max_cell,
        sum_cell_wall_s=sum_cell,
        problems=merged.problems, kpis=kpis,
        decomposed=len(part.cells) > 1)
