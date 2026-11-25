"""The compiler: canonical records -> solver-native problems (Stage 1)."""

from .router import RouteDecision, route
from .templates import (
    JobShopCompilation,
    LotSizingCompilation,
    compile_jobshop,
    compile_lotsizing,
)

__all__ = [
    "JobShopCompilation", "LotSizingCompilation", "RouteDecision",
    "compile_jobshop", "compile_lotsizing", "route",
]
