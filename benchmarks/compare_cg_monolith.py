"""CG-vs-monolith comparison, the ONLY sanctioned path for filing one.

usage: compare_cg_monolith.py CG_ROW.json MONO_ROW.json [--caps CAPS.json] [--out OUT.json]

Runs the weights guard first (weights_comparable or a named refusal; exit 2
on weights_differ_not_comparable, calibration_weights_not_comparable or
weights_not_recorded), then the pools identity check (exit 3 when the pools
hash differs or is missing), then prints the numbers. The verdicts appear in
the output by name. No number is printed before both guards passed."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "brain-core"))
from brain_core.guards.pool_identity import pools_hash  # noqa: E402
from brain_core.guards.weights_guard import (ComparisonRefused,  # noqa: E402
                                             require_comparable)


def caps_hash(path: str) -> str:
    d = json.loads(Path(path).read_text())
    sup = {tuple(json.loads(k)): v for k, v in d["sup"].items()}
    lab = {int(k): v for k, v in d["lab"].items()}
    return pools_hash(sup, lab)


def compare(cg: dict, mono: dict, caps_path: str | None = None) -> dict:
    wv = require_comparable(cg, mono, "cg_vs_monolith")   # raises
    mh = mono.get("pools_hash") or (caps_hash(caps_path) if caps_path
                                    else None)
    ch = cg.get("pools_hash")
    if not ch or not mh or ch != mh:
        raise ComparisonRefused(
            f"cg_vs_monolith: pools_differ_not_comparable (cg {ch}, "
            f"monolith {mh})")
    m_obj = mono.get("objective")
    lb, ub = cg.get("lower_bound"), cg.get("upper_bound")
    return {"weights_verdict": wv, "pools_verdict": "pools_same",
            "pools_hash": ch,
            "weights": cg["weights"] if "weights" in cg
            else cg.get("manifest", {}).get("weights"),
            "cg": {"status": cg.get("status"),
                   "iterations": cg.get("iterations"),
                   "lower_bound": lb, "upper_bound": ub,
                   "sha": cg.get("sha")},
            "monolith": {"status": mono.get("status"), "objective": m_obj,
                         "gap": mono.get("gap"), "sha": mono.get("sha"),
                         "limit_s": mono.get("limit_s"),
                         "wall_s": mono.get("wall_s")},
            "monolith_minus_cg_lb": (m_obj - lb) if (m_obj is not None
                                                     and lb is not None)
            else None,
            "cg_lb_not_above_monolith": (lb <= m_obj * (1 + 1e-9))
            if (m_obj is not None and lb is not None) else None}


def main(argv: list[str]) -> int:
    pos = [a for a in argv if not a.startswith("--")]
    opts = {argv[i]: argv[i + 1] for i, a in enumerate(argv[:-1])
            if a.startswith("--")}
    cg = json.loads(Path(pos[0]).read_text())
    mono = json.loads(Path(pos[1]).read_text())
    try:
        out = compare(cg, mono, opts.get("--caps"))
    except ComparisonRefused as e:
        msg = str(e)
        print("REFUSED " + msg)
        return 3 if "pools_differ" in msg else 2
    print(f"weights_verdict: {out['weights_verdict']}")
    print(f"pools_verdict: {out['pools_verdict']}")
    print(json.dumps(out, indent=1, default=str))
    if "--out" in opts:
        Path(opts["--out"]).write_text(json.dumps(out, indent=1,
                                                  default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
