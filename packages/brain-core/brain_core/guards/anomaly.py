"""Anomaly guard (guard 2): rules checked on every result record.

check_record returns a list of Finding(rule, detail). Any finding
means PAUSE: guarded_step stops the run, writes a fault record, and
only runs a fix action that was declared safe for that rule. Rules:
 class_mismatch     row manifest_hash != run manifest
 invalid_not_a_mip  solver=ipm/lp used for a MIP (nodes -1) or
                    int_violation > tol (integrality ignored)
 ub_not_validated   an upper bound is used while the independent
                    validator reported problems (or none ran)
 status_incoherent  status says optimal but gap > tol, or nodes < 0
 bound_crossed      lower bound above the incumbent (min problem)
 objective_mismatch the objective recomputed from the plan (guards.objective)
                    differs from the solver objective by > recon_tol
                    relative: a hidden or mis-weighted term
 nan_or_missing     NaN/inf or required field missing
Catches only these rules. A wrong model with a valid-looking result
passes; that needs an independent validator the rule cannot invent.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Finding:
    rule: str
    detail: str


REQUIRED = ("status", "incumbent")


def _walk_numbers(obj, path="", depth=0):
    """(path, float) for every real number in nested dicts/lists."""
    if depth > 6:
        return
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield path or "value", float(obj)
        return
    try:                                   # numpy scalars
        import numbers
        if isinstance(obj, numbers.Real):
            yield path or "value", float(obj)
            return
    except Exception:
        pass
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_numbers(v, f"{path}.{k}" if path else str(k),
                                     depth + 1)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _walk_numbers(v, f"{path}[{i}]", depth + 1)


def check_record(rec: dict, manifest_hash: str | None = None,
                 int_tol: float = 1e-6, gap_tol: float = 1e-4,
                 recon_tol: float = 1e-6):
    f = []
    for k in REQUIRED:
        if rec.get(k) is None:
            f.append(Finding("nan_or_missing", f"{k} missing"))
    # nested too: a NaN inside a per-plant list or a sub-dict (CG
    # rows, shard lists) used to pass because only top-level floats
    # were looked at
    for k, v in _walk_numbers(rec):
        if not math.isfinite(v):
            f.append(Finding("nan_or_missing", f"{k}={v}"))
    if manifest_hash is not None \
            and rec.get("manifest_hash") != manifest_hash:
        f.append(Finding("class_mismatch",
                         f"{rec.get('manifest_hash')!r} != "
                         f"{manifest_hash!r}"))
    iv = rec.get("int_violation")
    if (iv or 0.0) > int_tol or rec.get("mip_valid") is False:
        f.append(Finding("invalid_not_a_mip",
                         f"int_violation={iv}"))
    nodes = rec.get("nodes")
    if nodes is not None and nodes < 0:
        f.append(Finding("invalid_not_a_mip", f"nodes={nodes}"))
    if rec.get("ub_used"):
        probs = rec.get("validation_problems")
        if probs is None or len(probs) > 0:
            f.append(Finding("ub_not_validated",
                             f"validation_problems={probs!r}"))
    st = str(rec.get("status", "")).lower()
    gap = rec.get("mip_gap")
    if "optimal" in st and "not" not in st and gap is not None \
            and gap > gap_tol:
        f.append(Finding("status_incoherent",
                         f"optimal with gap {gap}"))
    lb, inc = rec.get("bound"), rec.get("incumbent")
    if lb is not None and inc is not None \
            and lb > inc + 1e-6 * max(1.0, abs(inc)):
        f.append(Finding("bound_crossed", f"lb {lb} > inc {inc}"))
    rec_o = rec.get("objective_reconciliation")
    if isinstance(rec_o, dict):
        a, b = rec_o.get("solver"), rec_o.get("recomputed")
        if not (isinstance(a, (int, float)) and isinstance(b, (int, float))
                and abs(a - b) <= recon_tol * max(1.0, abs(a))):
            f.append(Finding("objective_mismatch",
                             f"solver {a} vs recomputed from plan {b}"))
    return f


RULE_ORDER = ("class_mismatch", "nan_or_missing", "invalid_not_a_mip",
              "status_incoherent", "bound_crossed", "ub_not_validated",
              "objective_mismatch")


class RunPaused(RuntimeError):
    def __init__(self, findings):
        self.findings = findings
        super().__init__("PAUSED: " + "; ".join(
            f"{x.rule}({x.detail})" for x in findings))


def guarded_step(produce, manifest_hash=None, safe_fixes=None,
                 fault_log=None, max_fix_attempts=2):
    """produce() -> record. On findings: log fault, try the declared
    safe fix (a zero-arg callable that RETURNS A NEW RECORD) at most
    max_fix_attempts, else raise RunPaused. Never fixes a rule that has
    no declared safe fix. With findings of several rules, the fix of
    the first rule in RULE_ORDER runs; the record is then re-checked,
    so the next rule's fix gets its turn on the next attempt (before:
    fixes[0] always, i.e. by finding order, and the doc called the fix
    'a callable returning a new produce' while the code used it as a
    produce)."""
    safe_fixes = safe_fixes or {}
    rec = produce()
    for attempt in range(max_fix_attempts + 1):
        found = check_record(rec, manifest_hash)
        if not found:
            return rec
        if fault_log is not None:
            fault_log.append({"attempt": attempt,
                              "findings": [(x.rule, x.detail)
                                           for x in found]})
        fixes = [safe_fixes.get(x.rule) for x in found]
        if attempt == max_fix_attempts or not all(fixes):
            raise RunPaused(found)
        first = min(found, key=lambda x: RULE_ORDER.index(x.rule)
                    if x.rule in RULE_ORDER else len(RULE_ORDER))
        rec = safe_fixes[first.rule]()
    raise RunPaused(found)
