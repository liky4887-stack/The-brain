"""Domain records and pre-solve validation (blueprint layer 2).

Every input record is validated before any model is built; a problem that
fails validation never reaches a solver. Errors name the record and field.

Grounding: semantics per docs/model-spec.md. pydantic (MIT) does the field
mechanics; the RULES here (unique ids, positive weights, optional hard
deadline) come from docs/specs/stage0-tiny-problem.md, not from any library.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class Order(BaseModel):
    """One job to place on the machine."""

    id: str = Field(min_length=1)
    processing_time: int = Field(ge=0, description="minutes; zero allowed (instant step)")
    due_date: int = Field(ge=0, description="soft: lateness past it is penalized")
    weight: float = Field(gt=0, description="priority multiplier on lateness")
    deadline: Optional[int] = Field(default=None, ge=0, description="hard: completion after it is forbidden")


class Machine(BaseModel):
    """The single resource of the tiny problem."""

    id: str = Field(min_length=1)


class FactoryInput(BaseModel):
    """Raw planning input: one machine plus orders (Stage 0 scope)."""

    machine: Machine
    orders: List[Order] = Field(min_length=1)

    @field_validator("orders")
    @classmethod
    def unique_order_ids(cls, orders: List[Order]) -> List[Order]:
        seen = set()
        for order in orders:
            if order.id in seen:
                raise ValueError(f"duplicate order id: {order.id!r}")
            seen.add(order.id)
        return orders
