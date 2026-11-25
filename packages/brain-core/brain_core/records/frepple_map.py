"""Mapping from canonical records to frePPLe's input tables.

This is a SCHEMA CONTRACT, not frePPLe code: the table and column
names below mirror frePPLe's import CSV format so a Factory can be
pushed into the frePPLe UI (our data/screens layer, AGPL, kept out of
this repo) or exported as CSV rows. Verified against
freppledb/input/models/*.py (frePPLe 9.x development tree, Nov 2026).
"""

from __future__ import annotations

from .models import Factory


def _dur(td) -> str:
    """frePPLe CSV duration format: 'HH:MM:SS'."""
    total = int(td.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    return f"{sign}{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def frepple_rows(factory: Factory) -> dict[str, list[dict]]:
    """One list of row dicts per frePPLe input table (CSV-importable)."""
    tables: dict[str, list[dict]] = {
        "location": [], "item": [], "calendar": [], "setupmatrix": [],
        "setuprule": [], "resource": [], "operation": [],
        "operationmaterial": [], "operationresource": [], "buffer": [],
        "demand": [],
    }
    for l in factory.locations:
        tables["location"].append({
            "name": l.name, "description": l.description,
            "available": l.available_calendar or "",
        })
    for i in factory.items:
        tables["item"].append({
            "name": i.name, "description": i.description, "cost": i.cost,
        })
    for c in factory.calendars:
        tables["calendar"].append({"name": c.name, "default": c.default_value})
    for m in factory.setup_matrices:
        tables["setupmatrix"].append({"name": m.name})
        for r in m.rules:
            tables["setuprule"].append({
                "setupmatrix": m.name, "fromsetup": r.from_setup,
                "tosetup": r.to_setup, "duration": _dur(r.duration),
                "cost": r.cost,
            })
    for r in factory.resources:
        tables["resource"].append({
            "name": r.name, "location": r.location or "",
            "maximum": r.maximum,
            "maximum_calendar": r.maximum_calendar or "",
            "setupmatrix": r.setup_matrix or "", "efficiency": r.efficiency,
        })
    for op in factory.operations:
        tables["operation"].append({
            "name": op.name, "item": op.item or "",
            "location": op.location or "",
            "duration": _dur(op.duration),
            "duration_per": _dur(op.duration_per),
            "sizeminimum": op.size_minimum,
            "sizemultiple": op.size_multiple or "",
            "sizemaximum": op.size_maximum or "", "cost": op.cost,
        })
        for m in op.materials:
            tables["operationmaterial"].append({
                "operation": op.name, "item": m.item, "quantity": m.quantity,
            })
        for ld in op.loads:
            tables["operationresource"].append({
                "operation": op.name, "resource": ld.resource,
                "quantity": ld.quantity, "setup": ld.setup or "",
                "skill": ld.skill or "",
            })
    for b in factory.buffers:
        tables["buffer"].append({
            "item": b.item, "location": b.location, "onhand": b.onhand,
            "minimum": b.minimum, "maximum": b.maximum or "",
        })
    for d in factory.demands:
        tables["demand"].append({
            "name": d.name, "item": d.item, "location": d.location or "",
            "due": d.due.isoformat(), "quantity": d.quantity,
            "priority": d.priority, "minshipment": d.minshipment or "",
            "maxlateness": _dur(d.maxlateness) if d.maxlateness else "",
        })
    return tables
