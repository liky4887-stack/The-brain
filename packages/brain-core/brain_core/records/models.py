"""Canonical factory records — The-brain's single data model (Stage 1).

Every factory we plan for is described by these records. They map
one-to-one onto frePPLe's input tables (see frepple_map.py) so the
frePPLe UI can act as our data/screens layer, and they are the input
contract of the compiler (records -> solver-native problem).

Design rules honored here:
- frePPLe is AGPL: we reference its table/column NAMES as a schema
  contract only. No frePPLe code is vendored into this package.
- All quantities are Decimal-free at the solver boundary: scaling to
  integers happens in the compiler, never here (records stay
  human-scale floats/durations).
- Validation is independent of any solver (honesty rules).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Location(BaseModel):
    """frePPLe table: location."""
    name: str
    description: str = ""
    available_calendar: Optional[str] = None  # frePPLe: available


class Item(BaseModel):
    """frePPLe table: item (a product, intermediate, or raw material)."""
    name: str
    description: str = ""
    cost: float = 0.0


class Calendar(BaseModel):
    """Named availability calendar (frePPLe: calendar + calendarbuckets).

    Buckets are (start, end, value) windows inside a repeated week or
    explicit date ranges; value is a capacity multiplier (1.0 = fully
    available, 0.0 = down). Kept minimal here; the compiler expands
    buckets into per-period capacities.
    """
    name: str
    buckets: list[tuple[datetime, datetime, float]] = Field(default_factory=list)
    default_value: float = 1.0

    @model_validator(mode="after")
    def _buckets_ordered(self):
        for (s1, e1, _), (s2, e2, _) in zip(self.buckets, self.buckets[1:]):
            if s2 < e1:
                raise ValueError("overlapping calendar buckets")
        for s, e, v in self.buckets:
            if e <= s:
                raise ValueError("calendar bucket end must be after start")
            if v < 0:
                raise ValueError("calendar bucket value must be >= 0")
        return self


class SetupRule(BaseModel):
    """frePPLe table: setuprule (changeover from one setup to another)."""
    from_setup: str
    to_setup: str
    duration: timedelta
    cost: float = 0.0

    @model_validator(mode="after")
    def _duration_positive(self):
        if self.duration < timedelta(0):
            raise ValueError("setup duration must be >= 0")
        return self


class SetupMatrix(BaseModel):
    """frePPLe table: setupmatrix."""
    name: str
    rules: list[SetupRule] = Field(default_factory=list)

    def duration_between(self, from_setup: str, to_setup: str) -> Optional[timedelta]:
        if from_setup == to_setup:
            return timedelta(0)
        for r in self.rules:
            if r.from_setup == from_setup and r.to_setup == to_setup:
                return r.duration
        return None


class Resource(BaseModel):
    """frePPLe table: resource (a machine, line, or crew)."""
    name: str
    location: Optional[str] = None
    maximum: float = 1.0  # concurrent capacity units
    maximum_calendar: Optional[str] = None
    setup_matrix: Optional[str] = None
    efficiency: float = 1.0  # 1.0 = nominal speed


class OperationMaterial(BaseModel):
    """frePPLe table: operationmaterial (consumes/produces an item)."""
    item: str
    quantity: float  # negative = consume, positive = produce
    effective_start: Optional[datetime] = None
    effective_end: Optional[datetime] = None


class OperationResource(BaseModel):
    """frePPLe table: operationresource."""
    resource: str
    quantity: float = 1.0
    setup: Optional[str] = None  # setup state this load requires
    skill: Optional[str] = None


class Operation(BaseModel):
    """frePPLe table: operation (one way to make/move/buy an item)."""
    name: str
    item: Optional[str] = None
    location: Optional[str] = None
    duration: timedelta = timedelta(0)          # fixed part
    duration_per: timedelta = timedelta(0)      # per-unit part
    size_minimum: float = 1.0
    size_multiple: Optional[float] = None
    size_maximum: Optional[float] = None
    cost: float = 0.0
    materials: list[OperationMaterial] = Field(default_factory=list)
    loads: list[OperationResource] = Field(default_factory=list)
    effective_start: Optional[datetime] = None
    effective_end: Optional[datetime] = None

    @model_validator(mode="after")
    def _sizes_consistent(self):
        if self.size_minimum <= 0:
            raise ValueError("size_minimum must be > 0")
        if self.size_maximum is not None and self.size_maximum < self.size_minimum:
            raise ValueError("size_maximum must be >= size_minimum")
        if self.size_multiple is not None and self.size_multiple <= 0:
            raise ValueError("size_multiple must be > 0")
        if self.duration < timedelta(0) or self.duration_per < timedelta(0):
            raise ValueError("durations must be >= 0")
        return self


class Buffer(BaseModel):
    """frePPLe table: buffer (inventory of an item at a location)."""
    item: str
    location: str
    onhand: float = 0.0
    minimum: float = 0.0
    maximum: Optional[float] = None

    @model_validator(mode="after")
    def _levels_consistent(self):
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("buffer maximum must be >= minimum")
        if self.onhand < 0:
            raise ValueError("onhand must be >= 0")
        return self


class Demand(BaseModel):
    """frePPLe table: demand (a customer order or forecast line)."""
    name: str
    item: str
    location: Optional[str] = None
    due: datetime
    quantity: float
    priority: int = 1  # lower = more important (frePPLe convention)
    minshipment: Optional[float] = None
    maxlateness: Optional[timedelta] = None

    @model_validator(mode="after")
    def _quantity_positive(self):
        if self.quantity <= 0:
            raise ValueError("demand quantity must be > 0")
        if self.minshipment is not None and not 0 < self.minshipment <= self.quantity:
            raise ValueError("minshipment must be in (0, quantity]")
        if self.priority < 0:
            raise ValueError("priority must be >= 0")
        return self


class Factory(BaseModel):
    """The whole plant, one object in, one plan out.

    Reference integrity is checked here (no dangling names); solver
    feasibility is checked later by the compiler and the independent
    validator, never assumed from record validity alone.
    """
    locations: list[Location] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    calendars: list[Calendar] = Field(default_factory=list)
    setup_matrices: list[SetupMatrix] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    operations: list[Operation] = Field(default_factory=list)
    buffers: list[Buffer] = Field(default_factory=list)
    demands: list[Demand] = Field(default_factory=list)

    def validate_references(self) -> list[str]:
        """Human-readable list of broken references; empty when clean."""
        problems: list[str] = []
        loc = {l.name for l in self.locations}
        item = {i.name for i in self.items}
        cal = {c.name for c in self.calendars}
        mtx = {m.name for m in self.setup_matrices}
        res = {r.name for r in self.resources}
        if len(loc) != len(self.locations):
            problems.append("duplicate location names")
        if len(item) != len(self.items):
            problems.append("duplicate item names")
        if len(res) != len(self.resources):
            problems.append("duplicate resource names")
        for l in self.locations:
            if l.available_calendar and l.available_calendar not in cal:
                problems.append(f"location {l.name}: unknown calendar {l.available_calendar}")
        for r in self.resources:
            if r.location and r.location not in loc:
                problems.append(f"resource {r.name}: unknown location {r.location}")
            if r.maximum_calendar and r.maximum_calendar not in cal:
                problems.append(f"resource {r.name}: unknown calendar {r.maximum_calendar}")
            if r.setup_matrix and r.setup_matrix not in mtx:
                problems.append(f"resource {r.name}: unknown setup matrix {r.setup_matrix}")
            if r.maximum <= 0:
                problems.append(f"resource {r.name}: maximum must be > 0")
        for op in self.operations:
            if op.item and op.item not in item:
                problems.append(f"operation {op.name}: unknown item {op.item}")
            if op.location and op.location not in loc:
                problems.append(f"operation {op.name}: unknown location {op.location}")
            for m in op.materials:
                if m.item not in item:
                    problems.append(f"operation {op.name}: unknown material item {m.item}")
                if m.quantity == 0:
                    problems.append(f"operation {op.name}: zero-quantity material {m.item}")
            for ld in op.loads:
                if ld.resource not in res:
                    problems.append(f"operation {op.name}: unknown resource {ld.resource}")
                if ld.quantity <= 0:
                    problems.append(f"operation {op.name}: non-positive load on {ld.resource}")
        for b in self.buffers:
            if b.item not in item:
                problems.append(f"buffer ({b.item}@{b.location}): unknown item")
            if b.location not in loc:
                problems.append(f"buffer ({b.item}@{b.location}): unknown location")
        for d in self.demands:
            if d.item not in item:
                problems.append(f"demand {d.name}: unknown item {d.item}")
            if d.location and d.location not in loc:
                problems.append(f"demand {d.name}: unknown location {d.location}")
        return problems

    def producing_operations(self, item: str) -> list[Operation]:
        """Operations with a positive material flow of this item."""
        return [op for op in self.operations
                if any(m.item == item and m.quantity > 0 for m in op.materials)]
