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


def check_record(rec: dict, manifest_hash: str | None = None,
                 int_tol: float = 1e-6, gap_tol: float = 1e-4):
    f = []
    for k in REQUIRED:
        if rec.get(k) is None:
            f.append(Finding("nan_or_missing", f"{k} missing"))
    for k, v in rec.items():
        if isinstance(v, float) and not math.isfinite(v):
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
    return f


class RunPaused(RuntimeError):
    def __init__(self, findings):
        self.findings = findings
        super().__init__("PAUSED: " + "; ".join(
            f"{x.rule}({x.detail})" for x in findings))


def guarded_step(produce, manifest_hash=None, safe_fixes=None,
                 fault_log=None, max_fix_attempts=2):
    """produce() -> record. On findings: log fault, try the declared
    safe fix for each rule (a callable returning a new produce), at
    most max_fix_attempts, else raise RunPaused. Never fixes a rule
    that has no declared safe fix."""
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
        produce = fixes[0]
        rec = produce()
    raise RunPaused(found)
