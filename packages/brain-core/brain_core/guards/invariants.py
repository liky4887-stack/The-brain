"""Runtime invariants (guard 4): checked INSIDE every solve path.

The manifest, watchdog and anomaly guards run where a caller remembers
to call them (today: tests and benchmarks/monolith_scaling.py). These
checks are wired into the core functions themselves, so every plan the
engine returns - serving, ladder, decomposed, CG - has passed them:

 assignment_findings  a returned lot with a NaN/inf/<=0 quantity, a
                      day outside the window, a negative seq_pos, or
                      a NaN changeover (a NaN line total compared with
                      `total > cap` is False, so it used to pass the
                      capacity check silently)
 dw_bound_findings    CG: lower bound above the upper bound, NaN
                      bounds, a certified bound without convergence,
                      an upper bound with no plan behind it

Mode, from the BRAIN_GUARDS environment variable:
 record (default)  findings are returned and land in plan.problems,
                   so the plan is not counted as valid
 strict            the first finding raises InvariantViolation (the
                   run pauses at the wrong value instead of carrying
                   it into later windows)
 off               nothing is checked (for A/B timing only)
Catches only these rules; a plan that is wrong in a way the rules do
not name still needs the independent validator.
"""
from __future__ import annotations

import math
import os


class InvariantViolation(RuntimeError):
    pass


def mode() -> str:
    m = os.environ.get("BRAIN_GUARDS", "record").strip().lower()
    return m if m in ("record", "strict", "off") else "record"


def enforce(findings: list[str], where: str) -> list[str]:
    """record: return findings; strict: raise on any; off: []."""
    m = mode()
    if m == "off":
        return []
    if findings and m == "strict":
        raise InvariantViolation(f"invariant broken at {where}: "
                                 + "; ".join(findings[:5]))
    return findings


def _finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def assignment_findings(assignments, days: int, day0: int = 0,
                        limit: int = 20) -> list[str]:
    """Value/placement checks on returned LotAssignments."""
    if mode() == "off":
        return []
    out: list[str] = []
    for a in assignments:
        tag = f"{a.line} day {a.day} {a.sku}"
        if not _finite(a.qty) or a.qty <= 0:
            out.append(f"invariant: {tag}: qty {a.qty!r} not a "
                       "positive finite number")
        rel = a.day - day0
        if not (0 <= rel < days):
            out.append(f"invariant: {tag}: day outside window "
                       f"[{day0}, {day0 + days})")
        if not isinstance(a.seq_pos, int) or a.seq_pos < 0:
            out.append(f"invariant: {tag}: seq_pos {a.seq_pos!r}")
        if not _finite(a.chg_from_prev_min) or a.chg_from_prev_min < 0:
            out.append(f"invariant: {tag}: changeover "
                       f"{a.chg_from_prev_min!r}")
        if len(out) >= limit:
            out.append("invariant: further findings truncated")
            break
    return out


def dw_bound_findings(dw, rel_tol: float = 1e-6) -> list[str]:
    """Coherence of a DWResult's bounds (minimisation)."""
    if mode() == "off":
        return []
    out: list[str] = []
    lb, ub = dw.lower_bound, dw.upper_bound
    for name, v in (("lower_bound", lb), ("upper_bound", ub)):
        if v is not None and not _finite(v):
            out.append(f"invariant: {name} = {v!r}")
    if lb is not None and ub is not None and _finite(lb) \
            and _finite(ub) and lb > ub + rel_tol * max(1.0, abs(ub)):
        out.append(f"invariant: bound_crossed: lower bound {lb} > "
                   f"upper bound {ub} (a wrong dual, a wrong column "
                   "cost or an invalid plan)")
    if dw.bound_certified and not dw.converged:
        out.append("invariant: bound_certified without convergence")
    if ub is not None and not dw.selected_qtys:
        out.append("invariant: upper bound with no selected plan")
    return out
