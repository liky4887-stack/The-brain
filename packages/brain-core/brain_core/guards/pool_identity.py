"""Pool identity and the cross-row comparison guard.

Two rows for "the same seed" are the same INSTANCE only if they used the
same pools (supplier + labor caps). Pools depend on the linking-M version
they were computed under (caps-v1 vs caps-v2 differ per entry even when the
totals match, measured on seed 400012), so a seed number alone is not an
identity. `pools_hash` is the identity; every CG / monolith / bound row
must carry it.

`compare_to_pool_bound(row, bound)` is run before a row is written or
printed:
  - pools hashes differ or are missing -> Finding("pools_differ_not_comparable"):
    a finding of its own, never a silent pass and never a false
    "below physical bound" alarm across classes.
  - same pools and the row's claimed OBJECTIVE (kind "plan_objective", a
    plan's cost, or "converged_lp", the exact LP value of a converged
    master) is below late_weight x lateness lower bound by more than rel_tol
    -> Finding("below_physical_bound_pool"). Valid for a converged LP
    because the cumulative shortfall is convex and the bound relaxes more
    constraints. A "lower_bound" claim (e.g. a certified Farley bound) may
    legitimately sit below it (a weak bound is valid), so it is only
    checked for "pools differ", never for "below".
Assumptions of the bound: see guards.physical_bound."""
from __future__ import annotations

import hashlib
import json

from .anomaly import Finding, LATENESS_BOUND_REL_TOL

OBJECTIVE_KINDS = ("plan_objective", "converged_lp")


def pools_hash(supplier_cap: dict | None, labor_cap: dict | None) -> str:
    """Canonical identity of a pool set (key types normalised, values
    rounded to 9 significant digits so float noise does not split it)."""
    sup = sorted((json.dumps(list(k) if isinstance(k, (tuple, list)) else k),
                  float(f"{v:.9g}")) for k, v in (supplier_cap or {}).items()
                 if v is not None)
    lab = sorted((int(k), float(f"{v:.9g}"))
                 for k, v in (labor_cap or {}).items() if v is not None)
    return hashlib.sha256(json.dumps([sup, lab]).encode()).hexdigest()[:16]


def compare_to_pool_bound(row: dict, bound: dict,
                          rel_tol: float = LATENESS_BOUND_REL_TOL) -> list:
    """row: {pools_hash, kind, objective}; bound: {pools_hash, lower_bound
    (lateness unit-days), late_weight}. Returns a list of Finding."""
    rh, bh = row.get("pools_hash"), bound.get("pools_hash")
    if not rh or not bh or rh != bh:
        return [Finding("pools_differ_not_comparable",
                        f"row pools {rh!r} vs bound pools {bh!r}: different "
                        "instance (or identity not recorded); no comparison "
                        "made")]
    if row.get("kind") not in OBJECTIVE_KINDS:
        return []
    obj = row.get("objective")
    need = bound["late_weight"] * bound["lower_bound"]
    if not isinstance(obj, (int, float)) or \
            obj < need - rel_tol * max(1.0, abs(need)):
        return [Finding("below_physical_bound_pool",
                        f"{row.get('kind')} {obj} below late_weight x "
                        f"lateness bound = {need} on the same pools")]
    return []
