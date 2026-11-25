"""CSV ingestion for canonical factory records (Stage 2, slice 3).

An Odoo/ERP export lands as one CSV per table (see TABLES for the
schema). `dump_csvs` writes that format from a Factory; `load_csvs`
reads it tolerantly: bad rows become findings and are skipped, never
silently coerced, and the load always ends in a data-quality score so
the planner sees "how much do I trust this export" before solving.

Design rules honored here:
- stdlib csv + pydantic only (DECISIONS 4: no new dependencies; the
  dlt/Pandera deviation from the roadmap is recorded in DECISIONS.md).
- Validation is row-level (pydantic) plus referential (this module);
  solver feasibility is still checked later, by the compiler and the
  independent validator.
- The score is a documented heuristic: 100 minus ERROR_W per error
  finding minus WARN_W per warning, floored at 0. It is a summary of
  the findings list, never a substitute for reading it.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from ..records.models import (Buffer, Calendar, Demand, Factory, Item,
                              Location, Operation, OperationMaterial,
                              OperationResource, Resource, SetupMatrix,
                              SetupRule)

ERROR_W = 5   # score weight of an error finding (row skipped / fatal)
WARN_W = 1    # score weight of a warning finding (row kept, defaulted)

# table -> (filename, [required columns], [optional columns with default])
TABLES: dict[str, tuple[str, list[str], dict[str, str]]] = {
    "locations": ("locations.csv", ["name"],
                  {"description": "", "available_calendar": ""}),
    "calendars": ("calendars.csv", ["name"], {"default_value": "1"}),
    "calendarbuckets": ("calendarbuckets.csv",
                        ["calendar", "start", "end", "value"], {}),
    "items": ("items.csv", ["name"],
              {"description": "", "cost": "0"}),
    "resources": ("resources.csv", ["name"],
                  {"location": "", "maximum": "1", "efficiency": "1",
                   "setupmatrix": "", "maximum_calendar": ""}),
    "setuprules": ("setuprules.csv",
                   ["matrix", "fromsetup", "tosetup", "duration_min"],
                   {"cost": "0"}),
    "operations": ("operations.csv", ["name"],
                   {"item": "", "location": "", "duration_min": "0",
                    "duration_per_min": "0", "size_minimum": "1",
                    "cost": "0"}),
    "operationloads": ("operationloads.csv", ["operation", "resource"],
                       {"quantity": "1", "setup": ""}),
    "operationmaterials": ("operationmaterials.csv",
                           ["operation", "item", "quantity"], {}),
    "buffers": ("buffers.csv", ["item", "location"],
                {"onhand": "0", "minimum": "0", "maximum": ""}),
    "demands": ("demands.csv", ["name", "item", "due", "quantity"],
                {"location": "", "priority": "1"}),
}


@dataclass(frozen=True)
class Finding:
    """One data-quality finding: what, where, why."""
    severity: str          # "error" | "warning"
    code: str              # stable machine-readable code
    table: str
    row: int               # 1-based data row in the CSV (0 = whole file)
    detail: str


@dataclass
class IngestReport:
    factory: Factory | None      # None only on fatal structural failure
    findings: list[Finding] = field(default_factory=list)
    score: float = 100.0
    rows_read: int = 0
    rows_kept: int = 0

    def finalize(self) -> "IngestReport":
        errors = sum(1 for f in self.findings if f.severity == "error")
        warnings = sum(1 for f in self.findings if f.severity == "warning")
        self.score = max(0.0, 100.0 - ERROR_W * errors - WARN_W * warnings)
        return self


def _parse_float(raw: str, table: str, row: int, col: str,
                 findings: list[Finding]) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        findings.append(Finding("error", "bad-number", table, row,
                                f"column {col!r}: {raw!r} is not a number"))
        return None


def _parse_due(raw: str, table: str, row: int,
               findings: list[Finding]) -> datetime | None:
    raw = raw.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        findings.append(Finding("error", "bad-date", table, row,
                                f"due {raw!r} is not an ISO date"))
        return None


def _read_rows(path: Path, table: str,
               findings: list[Finding]) -> list[dict[str, str]]:
    """Rows of one CSV with defaults applied; missing file -> []."""
    if not path.exists():
        return []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            findings.append(Finding("error", "empty-file", table, 0,
                                    f"{path.name} has no header row"))
            return []
        fname, required, optional = TABLES[table]
        missing = [c for c in required if c not in reader.fieldnames]
        if missing:
            findings.append(Finding("error", "missing-column", table, 0,
                                    f"{path.name} lacks required "
                                    f"column(s): {', '.join(missing)}"))
            return []
        rows = []
        for raw in reader:
            row = {k: (v or "").strip() for k, v in raw.items() if k}
            for col, default in optional.items():
                if not row.get(col):
                    row[col] = default
            rows.append(row)
        return rows


def load_csvs(directory: str | Path) -> IngestReport:
    """Read every known CSV in `directory` into a validated Factory.

    Tolerant per row: an invalid row is dropped with an error finding;
    referential problems (unknown names) drop the referring row. What
    survives constructs a Factory, whose own pydantic validators run
    too; a failure there is fatal (factory=None), never hidden.
    """
    directory = Path(directory)
    report = IngestReport(factory=None)
    findings = report.findings
    raw: dict[str, list[dict[str, str]]] = {}
    for table, (fname, _, _) in TABLES.items():
        rows = _read_rows(directory / fname, table, findings)
        raw[table] = rows
        report.rows_read += len(rows)

    def build(rows, table, maker):
        """maker(row, rowno) -> record | None; counts kept rows."""
        out = []
        for i, row in enumerate(rows, start=1):
            rec = maker(row, i)
            if rec is not None:
                out.append(rec)
                report.rows_kept += 1
        return out

    def unique(records, table, key):
        seen, out = set(), []
        for r in records:
            k = key(r)
            if k in seen:
                findings.append(Finding(
                    "error", "duplicate-key", table, 0,
                    f"duplicate {k!r}; later rows skipped"))
            else:
                seen.add(k)
                out.append(r)
        return out

    def make_location(r, n):
        try:
            return Location(name=r["name"], description=r["description"],
                            available_calendar=r["available_calendar"]
                            or None)
        except ValidationError as exc:
            findings.append(Finding("error", "invalid-row", "locations",
                                    n, str(exc).splitlines()[0]))
            return None

    def make_calendar(r, n):
        dv = _parse_float(r["default_value"], "calendars", n,
                          "default_value", findings)
        if dv is None:
            return None
        try:
            return Calendar(name=r["name"], default_value=dv)
        except ValidationError as exc:
            findings.append(Finding("error", "invalid-row", "calendars",
                                    n, str(exc).splitlines()[0]))
            return None

    def make_bucket(r, n):
        start = _parse_due(r["start"], "calendarbuckets", n, findings)
        end = _parse_due(r["end"], "calendarbuckets", n, findings)
        val = _parse_float(r["value"], "calendarbuckets", n, "value",
                           findings)
        if start is None or end is None or val is None:
            return None
        return (r["calendar"], (start, end, val))

    def make_item(r, n):
        cost = _parse_float(r["cost"], "items", n, "cost", findings)
        if cost is None:
            return None
        try:
            return Item(name=r["name"], description=r["description"],
                        cost=cost)
        except ValidationError as exc:
            findings.append(Finding("error", "invalid-row", "items", n,
                                    str(exc).splitlines()[0]))
            return None

    def make_resource(r, n):
        mx = _parse_float(r["maximum"], "resources", n, "maximum",
                          findings)
        eff = _parse_float(r["efficiency"], "resources", n, "efficiency",
                           findings)
        if mx is None or eff is None:
            return None
        try:
            return Resource(name=r["name"], location=r["location"] or None,
                            maximum=mx, efficiency=eff,
                            setup_matrix=r["setupmatrix"] or None,
                            maximum_calendar=r["maximum_calendar"] or None)
        except ValidationError as exc:
            findings.append(Finding("error", "invalid-row", "resources",
                                    n, str(exc).splitlines()[0]))
            return None

    def make_setuprule(r, n):
        dur = _parse_float(r["duration_min"], "setuprules", n,
                           "duration_min", findings)
        cost = _parse_float(r["cost"], "setuprules", n, "cost", findings)
        if dur is None or cost is None:
            return None
        if dur < 0:
            findings.append(Finding("error", "negative-duration",
                                    "setuprules", n,
                                    f"duration_min {dur} < 0"))
            return None
        return (r["matrix"], SetupRule(from_setup=r["fromsetup"],
                                       to_setup=r["tosetup"],
                                       duration=timedelta(minutes=dur),
                                       cost=cost))

    def make_operation(r, n):
        dur = _parse_float(r["duration_min"], "operations", n,
                           "duration_min", findings)
        per = _parse_float(r["duration_per_min"], "operations", n,
                           "duration_per_min", findings)
        smin = _parse_float(r["size_minimum"], "operations", n,
                            "size_minimum", findings)
        cost = _parse_float(r["cost"], "operations", n, "cost", findings)
        if None in (dur, per, smin, cost):
            return None
        try:
            return Operation(name=r["name"], item=r["item"] or None,
                             location=r["location"] or None,
                             duration=timedelta(minutes=dur),
                             duration_per=timedelta(minutes=per),
                             size_minimum=smin, cost=cost)
        except ValidationError as exc:
            findings.append(Finding("error", "invalid-row", "operations",
                                    n, str(exc).splitlines()[0]))
            return None

    def make_buffer(r, n):
        onh = _parse_float(r["onhand"], "buffers", n, "onhand", findings)
        mn = _parse_float(r["minimum"], "buffers", n, "minimum", findings)
        mx = (_parse_float(r["maximum"], "buffers", n, "maximum", findings)
              if r["maximum"] else None)
        if onh is None or mn is None or (r["maximum"] and mx is None):
            return None
        try:
            return Buffer(item=r["item"], location=r["location"],
                          onhand=onh, minimum=mn, maximum=mx)
        except ValidationError as exc:
            findings.append(Finding("error", "invalid-row", "buffers", n,
                                    str(exc).splitlines()[0]))
            return None

    def make_demand(r, n):
        due = _parse_due(r["due"], "demands", n, findings)
        qty = _parse_float(r["quantity"], "demands", n, "quantity",
                           findings)
        prio = _parse_float(r["priority"], "demands", n, "priority",
                            findings)
        if due is None or qty is None or prio is None:
            return None
        try:
            return Demand(name=r["name"], item=r["item"], due=due,
                          quantity=qty, priority=int(prio),
                          location=r["location"] or None)
        except ValidationError as exc:
            findings.append(Finding("error", "invalid-row", "demands", n,
                                    str(exc).splitlines()[0]))
            return None

    calendars = unique(build(raw["calendars"], "calendars",
                             make_calendar), "calendars", lambda r: r.name)
    cal_by_name = {c.name: c for c in calendars}
    bucket_rows = build(raw["calendarbuckets"], "calendarbuckets",
                        make_bucket)
    cal_buckets: dict[str, list] = {}
    for cal_name, bucket in bucket_rows:
        if cal_name not in cal_by_name:
            findings.append(Finding("error", "unknown-calendar",
                                    "calendarbuckets", 0,
                                    f"bucket for calendar {cal_name!r} "
                                    "not in calendars.csv; skipped"))
            continue
        cal_buckets.setdefault(cal_name, []).append(bucket)
    calendars = [c.model_copy(update={
        "buckets": sorted(cal_buckets.get(c.name, []))})
        for c in calendars]
    calendar_names = set(cal_by_name)

    locations = unique(build(raw["locations"], "locations", make_location),
                       "locations", lambda r: r.name)
    kept_locations = []
    for loc in locations:
        if loc.available_calendar and \
                loc.available_calendar not in calendar_names:
            findings.append(Finding("error", "unknown-calendar",
                                    "locations", 0,
                                    f"location {loc.name!r}: calendar "
                                    f"{loc.available_calendar!r} not in "
                                    "calendars.csv; reference dropped"))
            loc = loc.model_copy(update={"available_calendar": None})
        kept_locations.append(loc)
    locations = kept_locations
    items = unique(build(raw["items"], "items", make_item),
                   "items", lambda r: r.name)
    resources = unique(build(raw["resources"], "resources", make_resource),
                       "resources", lambda r: r.name)
    operations = unique(build(raw["operations"], "operations",
                              make_operation), "operations", lambda r: r.name)
    buffers = build(raw["buffers"], "buffers", make_buffer)
    demands = unique(build(raw["demands"], "demands", make_demand),
                     "demands", lambda r: r.name)

    rule_rows = build(raw["setuprules"], "setuprules", make_setuprule)
    matrices: dict[str, list[SetupRule]] = {}
    for mtx_name, rule in rule_rows:
        matrices.setdefault(mtx_name, []).append(rule)
    setup_matrices = [SetupMatrix(name=k, rules=v)
                      for k, v in sorted(matrices.items())]

    # attach loads / materials to their operations
    op_by_name = {o.name: o for o in operations}

    def make_load(r, n):
        if r["operation"] not in op_by_name:
            findings.append(Finding("error", "unknown-operation",
                                    "operationloads", n,
                                    f"operation {r['operation']!r} "
                                    "not in operations.csv"))
            return None
        qty = _parse_float(r["quantity"], "operationloads", n,
                           "quantity", findings)
        if qty is None:
            return None
        return (r["operation"],
                OperationResource(resource=r["resource"], quantity=qty,
                                  setup=r["setup"] or None))

    def make_material(r, n):
        if r["operation"] not in op_by_name:
            findings.append(Finding("error", "unknown-operation",
                                    "operationmaterials", n,
                                    f"operation {r['operation']!r} "
                                    "not in operations.csv"))
            return None
        qty = _parse_float(r["quantity"], "operationmaterials", n,
                           "quantity", findings)
        if qty is None:
            return None
        return (r["operation"],
                OperationMaterial(item=r["item"], quantity=qty))

    for op_name, load in build(raw["operationloads"], "operationloads",
                               make_load):
        op_by_name[op_name].loads.append(load)
    for op_name, mat in build(raw["operationmaterials"],
                              "operationmaterials", make_material):
        op_by_name[op_name].materials.append(mat)

    # referential checks against the kept rows
    item_names = {i.name for i in items}
    resource_names = {r.name for r in resources}
    matrix_names = set(matrices)
    states = {rule.to_setup for m in setup_matrices for rule in m.rules} | \
             {rule.from_setup for m in setup_matrices for rule in m.rules}

    kept_demands = []
    for d in demands:
        if d.item not in item_names:
            findings.append(Finding("error", "unknown-item", "demands", 0,
                                    f"demand {d.name!r}: item {d.item!r} "
                                    "not in items.csv"))
        else:
            kept_demands.append(d)
    kept_buffers = []
    for b in buffers:
        if b.item not in item_names:
            findings.append(Finding("error", "unknown-item", "buffers", 0,
                                    f"buffer for item {b.item!r} not in "
                                    "items.csv"))
        else:
            kept_buffers.append(b)
    kept_resources = []
    for r in resources:
        if r.maximum_calendar and r.maximum_calendar not in calendar_names:
            findings.append(Finding("error", "unknown-calendar",
                                    "resources", 0,
                                    f"resource {r.name!r}: calendar "
                                    f"{r.maximum_calendar!r} not in "
                                    "calendars.csv; reference dropped"))
            r = r.model_copy(update={"maximum_calendar": None})
        if r.setup_matrix and r.setup_matrix not in matrix_names:
            findings.append(Finding("error", "unknown-matrix", "resources",
                                    0, f"resource {r.name!r}: setup "
                                    f"matrix {r.setup_matrix!r} has no "
                                    "rules in setuprules.csv; matrix "
                                    "reference dropped"))
            r = r.model_copy(update={"setup_matrix": None})
        kept_resources.append(r)
    kept_operations = []
    for o in operations:
        if o.item and o.item not in item_names:
            findings.append(Finding("error", "unknown-item", "operations",
                                    0, f"operation {o.name!r}: item "
                                    f"{o.item!r} not in items.csv; "
                                    "operation skipped"))
            continue
        kept_loads = []
        for load in o.loads:
            if load.resource not in resource_names:
                findings.append(Finding("error", "unknown-resource",
                                        "operations", 0,
                                        f"operation {o.name!r}: resource "
                                        f"{load.resource!r} not in "
                                        "resources.csv; load dropped"))
                continue
            if load.setup and setup_matrices and load.setup not in states:
                findings.append(Finding(
                    "warning", "unknown-setup-state", "operations", 0,
                    f"operation {o.name!r}: setup state {load.setup!r} "
                    "appears in no setup matrix rule"))
            kept_loads.append(load)
        if len(kept_loads) != len(o.loads):
            o = o.model_copy(update={"loads": kept_loads})
        if not o.loads:
            findings.append(Finding("warning", "operation-without-load",
                                    "operations", 0,
                                    f"operation {o.name!r} loads no "
                                    "resource; nothing can schedule it"))
        kept_operations.append(o)

    try:
        factory = Factory(locations=locations, items=items,
                          calendars=calendars,
                          setup_matrices=setup_matrices,
                          resources=kept_resources, operations=kept_operations,
                          buffers=kept_buffers, demands=kept_demands)
    except ValidationError as exc:
        findings.append(Finding("error", "factory-invalid", "factory", 0,
                                str(exc).splitlines()[0]))
        return report.finalize()
    report.factory = factory
    return report.finalize()


def dump_csvs(factory: Factory, directory: str | Path) -> None:
    """Write a Factory as the CSV schema above (one file per table).

    Round-trip contract: load_csvs(dump_csvs(f)) reproduces f with a
    score of 100 and no findings.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    def write(fname, header, rows):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(rows)
        (directory / fname).write_text(buf.getvalue())

    write("locations.csv", ["name", "description",
                            "available_calendar"],
          [[l.name, l.description, l.available_calendar or ""] for l in
           sorted(factory.locations, key=lambda x: x.name)])
    write("calendars.csv", ["name", "default_value"],
          [[c.name, c.default_value] for c in
           sorted(factory.calendars, key=lambda x: x.name)])
    write("calendarbuckets.csv", ["calendar", "start", "end", "value"],
          [[c.name, s.isoformat(timespec="seconds"),
            e.isoformat(timespec="seconds"), v]
           for c in sorted(factory.calendars, key=lambda x: x.name)
           for (s, e, v) in c.buckets])
    write("items.csv", ["name", "description", "cost"],
          [[i.name, i.description, i.cost] for i in
           sorted(factory.items, key=lambda x: x.name)])
    write("resources.csv",
          ["name", "location", "maximum", "efficiency", "setupmatrix",
           "maximum_calendar"],
          [[r.name, r.location or "", r.maximum, r.efficiency,
            r.setup_matrix or "", r.maximum_calendar or ""] for r in
           sorted(factory.resources, key=lambda x: x.name)])
    write("setuprules.csv",
          ["matrix", "fromsetup", "tosetup", "duration_min", "cost"],
          [[m.name, r.from_setup, r.to_setup,
            r.duration.total_seconds() / 60.0, r.cost]
           for m in sorted(factory.setup_matrices, key=lambda x: x.name)
           for r in m.rules])
    write("operations.csv",
          ["name", "item", "location", "duration_min",
           "duration_per_min", "size_minimum", "cost"],
          [[o.name, o.item or "", o.location or "",
            o.duration.total_seconds() / 60.0,
            o.duration_per.total_seconds() / 60.0,
            o.size_minimum, o.cost] for o in
           sorted(factory.operations, key=lambda x: x.name)])
    write("operationloads.csv",
          ["operation", "resource", "quantity", "setup"],
          [[o.name, l.resource, l.quantity, l.setup or ""]
           for o in sorted(factory.operations, key=lambda x: x.name)
           for l in o.loads])
    write("operationmaterials.csv", ["operation", "item", "quantity"],
          [[o.name, m.item, m.quantity]
           for o in sorted(factory.operations, key=lambda x: x.name)
           for m in o.materials])
    write("buffers.csv",
          ["item", "location", "onhand", "minimum", "maximum"],
          [[b.item, b.location, b.onhand, b.minimum,
            "" if b.maximum is None else b.maximum]
           for b in sorted(factory.buffers,
                           key=lambda x: (x.item, x.location))])
    write("demands.csv",
          ["name", "item", "due", "quantity", "location", "priority"],
          [[d.name, d.item, d.due.isoformat(timespec="seconds"),
            d.quantity, d.location or "", d.priority]
           for d in sorted(factory.demands, key=lambda x: x.name)])
