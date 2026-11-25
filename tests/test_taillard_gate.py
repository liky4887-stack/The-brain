"""Stage 1 gate: Taillard ta01-ta10 within 5% of optimum in 60s each.

ROADMAP Stage 1 gate. Instances: ScheduleOpt/benchmarks (Taillard 1993,
EJOR 64:278-285), tests/data/taillard/ta01..ta10.json. Optima are the
proven values (LB=UB) confirmed by two independent trackers
(optimizizer.com/TA.php and the ScheduleOpt table): ta01=1231,
ta02=1244, ta03=1218, ta04=1175, ta05=1224, ta06=1238, ta07=1227,
ta08=1217, ta09=1274, ta10=1241.

Every makespan is recomputed by the independent disjunctive-graph
validator, never taken from the solver's word. Marked "benchmark":
excluded from the regular suite (each instance may use its full 60s),
run with: python3 -m pytest tests/test_taillard_gate.py -m benchmark
"""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.jobshop.cpsat_solver import solve_jobshop
from brain_core.jobshop.disjunctive import JobShopInstance

DATA = Path(__file__).parent / "data" / "taillard"

OPTIMA = {"ta01": 1231, "ta02": 1244, "ta03": 1218, "ta04": 1175,
          "ta05": 1224, "ta06": 1238, "ta07": 1227, "ta08": 1217,
          "ta09": 1274, "ta10": 1241}


def load(name: str) -> JobShopInstance:
    d = json.loads((DATA / f"{name}.json").read_text())
    routes = {}
    for o in sorted(d["operations"], key=lambda o: (o["job"], o["step"])):
        routes.setdefault(o["job"], []).append((str(o["machine"]),
                                                o["duration"]))
    return JobShopInstance(tuple(tuple(r) for _, r in sorted(routes.items())))


@pytest.mark.benchmark
@pytest.mark.parametrize("name,optimum", sorted(OPTIMA.items()))
def test_taillard_gate(name, optimum):
    t0 = time.time()
    res = solve_jobshop(load(name), time_limit_s=60.0)
    elapsed = time.time() - t0
    assert res.validated, "plan must pass the independent validator"
    assert res.makespan is not None, f"{name}: no feasible plan in 60s"
    gap = (res.makespan - optimum) / optimum
    print(f"\n{name}: {res.makespan} (optimum {optimum}, gap {gap:.2%}, "
          f"{res.status}, {elapsed:.1f}s)")
    assert gap <= 0.05, f"{name}: gap {gap:.2%} exceeds the 5% gate"
