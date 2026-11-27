"""HiGHS MIP path (via scipy's bundled HiGHS) + a minimal MPS reader.

Purpose: the MIPLIB regression gate of Stage 1 (ROADMAP). The router
sends pure linear integer problems here (CP-SAT Primer: CP-SAT is not
an LP/MIP solver); MIPLIB keeps that path honest against literature
optima.

Licenses: scipy bundles HiGHS (MIT); scipy itself is BSD-3. Both are
compatible with The-brain (no AGPL).

The MPS reader covers the fixed-record subset used by MIPLIB 3.0:
ROWS (N/L/G/E), COLUMNS with INTORG/INTEND markers, RHS, BOUNDS
(UP/LO/FX/FR/MI/PL/BV), ENDATA. It deliberately refuses anything else
(SETS/SOS/RANGES) rather than parsing it wrong (honesty rules).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class MIP:
    """min c^T x s.t. row_sense rows; lb <= x <= ub; integrality flags."""
    name: str
    c: np.ndarray
    A: np.ndarray          # (n_rows, n_vars)
    sense: tuple           # per row: "L" | "G" | "E"
    rhs: np.ndarray
    lb: np.ndarray
    ub: np.ndarray
    integrality: np.ndarray  # 1 = integer
    row_family: Optional[tuple] = None  # per row: constraint-family name


def read_mps(path: str) -> MIP:
    with open(path) as fh:
        lines = [ln.rstrip("\n") for ln in fh if not ln.startswith("*")]
    name = ""
    section = None
    obj = None
    row_names, senses = [], []
    col_names: list[str] = []
    col_idx: dict[str, int] = {}
    entries: list[tuple[int, int, float]] = []
    obj_entries: list[tuple[int, float]] = []
    rhs: dict[str, float] = {}
    lb: dict[str, float] = {}
    ub: dict[str, float] = {}
    integers: set[str] = set()
    in_integer = False
    for ln in lines:
        if ln[:1].strip():  # section header (column 0 non-space)
            section = ln.split()[0]
            if section == "NAME":
                name = ln.split(None, 1)[1].strip() if len(ln.split()) > 1 else ""
            if section not in ("NAME", "ROWS", "COLUMNS", "RHS",
                               "BOUNDS", "ENDATA"):
                raise ValueError(f"unsupported MPS section {section} in {path}")
            continue
        parts = ln.split()
        if section == "ROWS":
            sense, rname = parts[0], parts[1]
            if sense == "N":
                if obj is None:
                    obj = rname
                # additional free rows are ignored (standard practice)
            else:
                if sense not in ("L", "G", "E"):
                    raise ValueError(f"unsupported row sense {sense}")
                row_names.append(rname)
                senses.append(sense)
        elif section == "COLUMNS":
            if any("MARKER" in tok for tok in parts):
                in_integer = any("INTORG" in tok for tok in parts)
                continue
            cname = parts[0]
            if cname not in col_idx:
                col_idx[cname] = len(col_names)
                col_names.append(cname)
            if in_integer:
                integers.add(cname)
            pairs = parts[1:]
            for i in range(0, len(pairs), 2):
                rname, val = pairs[i], float(pairs[i + 1])
                if rname == obj:
                    obj_entries.append((col_idx[cname], val))
                else:
                    entries.append((row_names.index(rname),
                                    col_idx[cname], val))
        elif section == "RHS":
            pairs = parts[1:]
            for i in range(0, len(pairs), 2):
                rhs[pairs[i]] = float(pairs[i + 1])
        elif section == "BOUNDS":
            btype, _set, cname = parts[0], parts[1], parts[2]
            val = float(parts[3]) if len(parts) > 3 else None
            if btype == "UP":
                ub[cname] = val
            elif btype == "LO":
                lb[cname] = val
            elif btype == "FX":
                lb[cname] = ub[cname] = val
            elif btype == "FR":
                lb[cname], ub[cname] = -np.inf, np.inf
            elif btype == "MI":
                lb[cname] = -np.inf
            elif btype == "PL":
                ub[cname] = np.inf
            elif btype == "BV":
                lb[cname], ub[cname] = 0.0, 1.0
                integers.add(cname)
            elif btype in ("UI", "LI"):
                if btype == "UI":
                    ub[cname] = val
                else:
                    lb[cname] = val
                integers.add(cname)
            else:
                raise ValueError(f"unsupported bound type {btype}")
    n_v, n_r = len(col_names), len(row_names)
    c = np.zeros(n_v)
    for j, v in obj_entries:
        c[j] = v
    A = np.zeros((n_r, n_v))
    for i, j, v in entries:
        A[i, j] = v
    r = np.array([rhs.get(rn, 0.0) for rn in row_names])
    lower = np.array([lb.get(cn, 0.0) for cn in col_names])
    upper = np.array([ub.get(cn, np.inf) for cn in col_names])
    integ = np.array([1 if cn in integers else 0 for cn in col_names])
    return MIP(name, c, A, tuple(senses), r, lower, upper, integ)


def solve_mip(mip: MIP, time_limit_s: float = 60.0,
              mip_rel_gap: float = 0.0) -> dict:
    """Solve with HiGHS via scipy.optimize.milp. Honest statuses:
    objective is recomputed from the returned x, never trusted from
    the solver's fun field alone."""
    from scipy.optimize import Bounds, LinearConstraint, milp
    lo = np.where(np.array(mip.sense) == "G", mip.rhs, -np.inf)
    hi = np.where(np.array(mip.sense) == "L", mip.rhs, np.inf)
    eq = np.array(mip.sense) == "E"
    lo[eq] = hi[eq] = mip.rhs[eq]
    res = milp(mip.c, integrality=mip.integrality,
               bounds=Bounds(mip.lb, mip.ub),
               constraints=LinearConstraint(mip.A, lo, hi),
               options={"time_limit": time_limit_s,
                        "mip_rel_gap": mip_rel_gap})
    if res.x is None:
        return {"status": res.message, "objective": None, "x": None}
    objective = float(mip.c @ res.x)  # recomputed from the assignment
    return {"status": res.message, "objective": objective, "x": res.x,
            "node_count": getattr(res, "mip_node_count", None),
            "gap": getattr(res, "mip_gap", None)}


def _milp_feasible(mip: MIP, keep: np.ndarray, time_limit_s: float):
    """Feasibility of the rows in `keep` only: True / False / None (undecided)."""
    from scipy.optimize import Bounds, LinearConstraint, milp
    sense = np.array(mip.sense)
    lo = np.where(sense == "G", mip.rhs, -np.inf)
    hi = np.where(sense == "L", mip.rhs, np.inf)
    eq = sense == "E"
    lo[eq] = hi[eq] = mip.rhs[eq]
    res = milp(np.zeros(len(mip.c)), integrality=mip.integrality,
               bounds=Bounds(mip.lb, mip.ub),
               constraints=LinearConstraint(mip.A[keep], lo[keep], hi[keep]),
               options={"time_limit": time_limit_s})
    if res.status == 0:
        return True
    if res.status == 2:
        return False
    return None


RATIO_RHS_FLOOR = 1.0   # |rhs| below this: ratio denominator is this floor (flagged)


def explain_infeasible_mip(mip: MIP, time_limit_s: float = 30.0,
                           slack_weights: Optional[np.ndarray] = None,
                           normalize: bool = False) -> dict:
    """Name WHAT conflicts and HOW MUCH is missing, at constraint-FAMILY level.

    Needs mip.row_family (one name per row). Two parts, both stated as
    family-level, never row-level:
    1. Elastic model: every row gets a nonnegative slack (both directions
       for E rows) and the weighted total slack is minimized (integrality
       kept). Weight per row defaults to 1, so a row's slack is in that
       ROW's own units; amounts are comparable inside a family (same units)
       and NOT across families. The minimum is one optimal repair, not the
       only one. Reported: per family the total slack and the rows with
       slack > 1e-9 (row index, amount).
    2. Deletion filter over families: drop a whole family, keep the drop
       when the remaining families stay INFEASIBLE. The result is a
       minimal set of FAMILIES (removing any one family makes the rest
       feasible); it does not say which rows inside a family conflict.
    Each slack row is reported with its absolute amount (row units) AND a
    relative violation ratio = slack / max(|rhs|, RATIO_RHS_FLOOR). For a
    row with |rhs| < RATIO_RHS_FLOOR (zero or tiny rhs) the denominator is
    the floor, so the ratio equals the absolute amount, and the row is
    flagged ratio_basis="floor". normalize=True also minimizes the ratio
    (weights 1/denominator) instead of the absolute amounts; the ratio is
    scale-free but depends on the rhs size, so it is a comparison aid, not
    a cost.
    An undecided solve is reported as "undecided", never as a result.
    Not applied to feasible problems: call it only after INFEASIBLE.
    """
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import csr_matrix, hstack, identity
    if mip.row_family is None:
        raise ValueError("MIP has no row_family labels")
    fam = np.array(mip.row_family)
    m, n = mip.A.shape
    sense = np.array(mip.sense)
    denom = np.maximum(np.abs(mip.rhs), RATIO_RHS_FLOOR)
    w = np.ones(m) if slack_weights is None else np.asarray(slack_weights, float)
    if normalize and slack_weights is None:
        w = 1.0 / denom
    # columns: x, s_minus (for L/E: a x - s <= rhs), s_plus (for G/E: a x + s >= rhs)
    I = identity(m, format="csr")
    A = hstack([csr_matrix(mip.A), -I, I], format="csr")
    lo = np.where(sense == "G", mip.rhs, -np.inf)
    hi = np.where(sense == "L", mip.rhs, np.inf)
    eq = sense == "E"
    lo[eq] = hi[eq] = mip.rhs[eq]
    # s_minus only meaningful for L/E rows, s_plus for G/E rows
    ub_minus = np.where(sense == "G", 0.0, np.inf)
    ub_plus = np.where(sense == "L", 0.0, np.inf)
    c = np.concatenate([np.zeros(n), w, w])
    lb = np.concatenate([mip.lb, np.zeros(2 * m)])
    ub = np.concatenate([mip.ub, ub_minus, ub_plus])
    integ = np.concatenate([mip.integrality, np.zeros(2 * m)])
    res = milp(c, integrality=integ, bounds=Bounds(lb, ub),
               constraints=LinearConstraint(A, lo, hi),
               options={"time_limit": time_limit_s})
    out = {"level": "family", "slack_by_family": {}, "slack_rows": [],
           "minimal_families": None, "notes": []}
    if res.x is None:
        out["notes"].append(f"elastic model undecided: {res.message}")
    else:
        sl = res.x[n:n + m] + res.x[n + m:]
        for i in np.nonzero(sl > 1e-9)[0]:
            out["slack_rows"].append({
                "row": int(i), "family": str(fam[i]), "amount": float(sl[i]),
                "ratio": float(sl[i] / denom[i]),
                "ratio_basis": "rhs" if abs(mip.rhs[i]) >= RATIO_RHS_FLOOR else "floor"})
            out["slack_by_family"][str(fam[i])] = \
                out["slack_by_family"].get(str(fam[i]), 0.0) + float(sl[i])
        out["slack_weights"] = ("1/max(|rhs|,floor) (ratio)" if normalize else
                                "1 per row unit (row's own units; not comparable across families)")
        fr = {}
        for r_ in out["slack_rows"]:
            fr[r_["family"]] = max(fr.get(r_["family"], 0.0), r_["ratio"])
        out["worst_ratio_by_family"] = fr
        if res.status != 0:
            out["notes"].append("elastic solve not proven optimal: amounts are an upper bound on the minimum")
    names = sorted(set(fam.tolist()))
    if _milp_feasible(mip, np.ones(m, bool), time_limit_s) is not False:
        out["notes"].append("problem not proven infeasible: no family set named")
        return out
    core = set(names)
    for f in names:
        trial = core - {f}
        keep = np.isin(fam, list(trial))
        r = _milp_feasible(mip, keep, time_limit_s)
        if r is False:
            core = trial
        elif r is None:
            out["notes"].append(f"family {f!r}: re-solve undecided, set may be unminimized")
    out["minimal_families"] = sorted(core)
    return out
