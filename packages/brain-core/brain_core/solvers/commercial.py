"""Optional commercial-solver pass-through (Stage 4, slice 8).

The architecture stays solver-neutral: when a client buys a Gurobi
or CPLEX license, their solver takes the SAME MIP object through an
adapter, and the answer comes back through the same recomputation and
validation as HiGHS. When no commercial binding is installed, the
pass-through says so honestly (UNAVAILABLE) - it never silently
substitutes another solver and never invents a result.

The adapter protocol is one function:

    adapter(mip: MIP, time_limit_s: float, mip_rel_gap: float)
        -> {"status": str, "objective": float | None, "x": array | None}

Register real bindings with register_adapter("gurobi", fn). The
objective of any returned x is ALWAYS recomputed from mip.c here, so
an adapter's claimed objective is ignored (decision 5).
"""

from __future__ import annotations

import numpy as np

from .highs_mip import MIP

_ADAPTERS: dict[str, object] = {}


def register_adapter(name: str, fn) -> None:
    """Register a commercial binding's adapter function."""
    _ADAPTERS[name] = fn


def available_solvers() -> list[str]:
    """Commercial solvers whose bindings are actually importable
    (registered) right now."""
    return sorted(_ADAPTERS)


def solve_mip_commercial(mip: MIP, solver: str,
                         time_limit_s: float = 60.0,
                         mip_rel_gap: float = 0.0) -> dict:
    """Hand the MIP to a registered commercial adapter; recompute
    the objective from the returned x, exactly like solve_mip does.
    """
    fn = _ADAPTERS.get(solver)
    if fn is None:
        return {"status": f"UNAVAILABLE: no adapter registered for "
                          f"{solver!r} (available: "
                          f"{available_solvers() or 'none'})",
                "objective": None, "x": None}
    res = fn(mip, time_limit_s=time_limit_s, mip_rel_gap=mip_rel_gap)
    x = res.get("x")
    if x is None:
        return {"status": str(res.get("status", "ERROR")),
                "objective": None, "x": None}
    x = np.asarray(x, dtype=float)
    if len(x) != len(mip.c):
        return {"status": f"ERROR: adapter returned {len(x)} values "
                          f"for {len(mip.c)} variables",
                "objective": None, "x": None}
    objective = float(mip.c @ x)      # recomputed, never trusted
    return {"status": str(res.get("status", "OK")),
            "objective": objective, "x": x}
