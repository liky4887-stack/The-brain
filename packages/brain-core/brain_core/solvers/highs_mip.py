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
              mip_rel_gap: float = 0.0,
              node_limit: int | None = None) -> dict:
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
               options=({"time_limit": time_limit_s,
                         "mip_rel_gap": mip_rel_gap}
                        | ({"node_limit": int(node_limit)}
                           if node_limit else {})))
    if res.x is None:
        return {"status": res.message, "objective": None, "x": None}
    objective = float(mip.c @ res.x)  # recomputed from the assignment
    return {"status": res.message, "objective": objective, "x": res.x,
            "node_count": getattr(res, "mip_node_count", None),
            "gap": getattr(res, "mip_gap", None)}
