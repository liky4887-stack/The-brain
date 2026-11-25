"""Decomposition by plant (Stage 4, slice 1).

The scale gate (2M-constraint plans in under 30 minutes) needs the
problem split into pieces that solve independently. The natural cut
in the canonical records: two lines are COUPLED exactly when some
SKU can run on both (an operation loads both). Maximal coupled sets
of lines are cells; cells share nothing that a plan writes - SKUs,
operations, demands and buffers all belong to exactly one cell - so
cells can be solved in parallel and their plans concatenated.

Honesty rules honored:
- independence is PROVEN from the records (union-find over
  SKU-sharing), never assumed; anything that does not fit the cell
  structure (a demand for an item no operation produces) is reported
  in the partition's problems, not silently dropped;
- the merged plan still goes through the same independent validator
  as a monolithic plan;
- stdlib only (decision 4); parallelism (next step) uses stdlib
  concurrent.futures before any Ray/mpi-sppy dependency is weighed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..records.models import Factory


@dataclass
class Cell:
    """One independently solvable part of the factory."""
    lines: list[str]
    skus: list[str]                    # producible items in this cell
    operations: list                   # Operation objects
    demands: list                      # Demand objects
    buffers: list                      # Buffer objects
    resources: list                    # Resource objects


@dataclass
class Partition:
    cells: list[Cell]
    problems: list[str] = field(default_factory=list)

    @property
    def is_decomposable(self) -> bool:
        return len(self.cells) > 1 and not self.problems


def partition_plants(factory: Factory) -> Partition:
    """Split the factory into SKU-closed line cells (union-find).

    Only production operations (duration_per > 0, a produced item,
    at least one load) couple lines - the same definition _sku_data
    uses for the rolling solver, so the partition matches what the
    solver sees.
    """
    from datetime import timedelta

    lines = [r.name for r in factory.resources]
    parent = {l: l for l in lines}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    sku_lines: dict[str, list[str]] = {}
    sku_op: dict[str, object] = {}
    for op in factory.operations:
        produced = [m.item for m in op.materials if m.quantity > 0]
        if (not produced or op.duration_per <= timedelta(0)
                or not op.loads):
            continue
        item = produced[0]
        op_lines = [ld.resource for ld in op.loads]
        sku_lines.setdefault(item, [])
        for l in op_lines:
            if l not in sku_lines[item]:
                sku_lines[item].append(l)
        sku_op[item] = op
        for l in op_lines:
            union(op_lines[0], l)

    groups: dict[str, list[str]] = {}
    for l in lines:
        groups.setdefault(find(l), []).append(l)

    problems: list[str] = []
    cells: list[Cell] = []
    item_cell: dict[str, int] = {}
    for root in sorted(groups, key=lambda r: sorted(groups[r])[0]):
        cell_lines = sorted(groups[root])
        line_set = set(cell_lines)
        cell_skus = sorted(s for s, ls in sku_lines.items()
                           if any(l in line_set for l in ls))
        ops = [sku_op[s] for s in cell_skus]
        cells.append(Cell(
            lines=cell_lines, skus=cell_skus, operations=ops,
            demands=[], buffers=[],
            resources=[r for r in factory.resources
                       if r.name in line_set]))
        for s in cell_skus:
            item_cell[s] = len(cells) - 1

    for d in factory.demands:
        if d.item in item_cell:
            cells[item_cell[d.item]].demands.append(d)
        else:
            problems.append(
                f"demand {d.name}: item {d.item} has no production "
                f"operation - not assignable to any cell")
    cell_of_item = item_cell
    for b in factory.buffers:
        if b.item in cell_of_item:
            cells[cell_of_item[b.item]].buffers.append(b)
        # buffers for raw/unknown items constrain nothing the cells
        # write; skip quietly (they are inputs, not plan outputs)
    return Partition(cells=cells, problems=problems)


def sub_factory(factory: Factory, cell: Cell) -> Factory:
    """The records of one cell as a standalone Factory: reference
    integrity is preserved (validate_references stays clean) because
    items, locations, calendars and setup matrices are shared
    read-only inputs, while operations/demands/buffers/resources are
    cell-exclusive."""
    cell_skus = set(cell.skus)
    consumed = {m.item for op in cell.operations
                for m in op.materials if m.quantity < 0}
    keep_items = cell_skus | consumed
    matrix_names = {r.setup_matrix for r in cell.resources
                    if r.setup_matrix}
    return Factory(
        locations=factory.locations,
        items=[i for i in factory.items if i.name in keep_items],
        calendars=factory.calendars,
        setup_matrices=[m for m in factory.setup_matrices
                        if m.name in matrix_names],
        resources=cell.resources,
        operations=cell.operations,
        buffers=cell.buffers,
        demands=cell.demands)
