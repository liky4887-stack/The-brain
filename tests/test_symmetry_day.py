"""Williams ch.6 symmetry breaking among identical lines (day model):
optimum preserved, permuted duplicates pruned, pinned lines exempt."""
import sys
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "packages" / "brain-core"))

from brain_core.records.models import (Buffer, Calendar, Demand, Factory,
                                       Item, Location, Operation,
                                       OperationMaterial, OperationResource,
                                       Resource, SetupMatrix, SetupRule)
from brain_core.rolling.two_level import (_identical_line_groups,
                                          solve_day_exact)

H0 = datetime(2026, 11, 30)


def sym_factory(lines, extra_elig=None, rules=None):
    """SKUs A,B; every SKU eligible on every line unless extra_elig
    restricts (sku -> lines)."""
    rules = rules or [SetupRule(from_setup="A-STATE", to_setup="B-STATE",
                                duration=timedelta(minutes=10)),
                      SetupRule(from_setup="B-STATE", to_setup="A-STATE",
                                duration=timedelta(minutes=40))]
    elig = extra_elig or {}
    ops = []
    for s in ("A", "B"):
        ls = elig.get(s, lines)
        ops.append(Operation(
            name=f"MAKE-{s}", item=s, location="P",
            duration_per=timedelta(minutes=1.0),
            materials=[OperationMaterial(item=s, quantity=1.0)],
            loads=[OperationResource(resource=l, quantity=1.0,
                                     setup=f"{s}-STATE") for l in ls]))
    f = Factory(locations=[Location(name="P")],
                items=[Item(name="A"), Item(name="B")],
                calendars=[Calendar(name="24x7")],
                setup_matrices=[SetupMatrix(name="M", rules=rules)],
                resources=[Resource(name=l, location="P", setup_matrix="M")
                           for l in lines],
                operations=ops,
                buffers=[Buffer(item="A", location="P"),
                         Buffer(item="B", location="P")],
                demands=[])
    assert f.validate_references() == []
    return f


def test_identical_line_grouping():
    f = sym_factory(["L1", "L2", "L3"], extra_elig={"A": ["L1", "L2"],
                                                    "B": ["L1", "L2"]})
    sku = {"A": (1.0, ["L1", "L2"], "A-STATE"),
           "B": (1.0, ["L1", "L2"], "B-STATE")}
    mtx = {r.name: m for m in f.setup_matrices
           for r in f.resources if r.setup_matrix == m.name}
    res_mtx = {r.name: mtx.get(r.setup_matrix) for r in f.resources}
    chunks = [("A", 10.0), ("B", 10.0)]
    groups = _identical_line_groups(["L1", "L2", "L3"], chunks, sku,
                                    res_mtx)
    # L1,L2 share eligibility+matrix; L3 eligible for nothing today:
    # with no day SKUs on it, its key differs -> singleton, not returned
    assert ["L1", "L2"] in groups
    assert all("L3" not in g for g in groups)


def brute_force_optimum(chunks, lines, prod_min, chg, cap):
    """Exact optimum by enumeration: assign each chunk to a line, per
    line choose the cheapest state tour (brute force over subsets and
    orders), respect capacity. Cost = production + changeover minutes
    (the day model's exact cost level)."""
    best = None
    for assign in product(range(len(lines)), repeat=len(chunks)):
        total = 0.0
        ok = True
        for li in range(len(lines)):
            states = sorted({chunks[i][0] for i in range(len(chunks))
                             if assign[i] == li})
            prod = sum(prod_min[chunks[i][0]] for i in range(len(chunks))
                       if assign[i] == li)
            if not states:
                continue
            # cheapest Hamiltonian path over the states present
            from itertools import permutations
            tour = min(sum(chg.get((a, b), 10**9)
                           for a, b in zip(p, p[1:]))
                       for k in range(1, len(states) + 1)
                       for p in permutations(states, k)
                       if set(p) == set(states))
            if prod + tour > cap:
                ok = False
                break
            total += prod + tour
        if ok and (best is None or total < best):
            best = total
    return best


def test_symmetry_breaking_preserves_optimum():
    f = sym_factory(["L1", "L2"])
    chunks = [("A", 30.0), ("B", 20.0)]
    asg, problems = solve_day_exact(f, chunks, 0, 100.0,
                                    time_limit_s=5.0)
    assert problems == []
    prod = {"A": 30, "B": 20}
    chg = {("A", "B"): 10, ("B", "A"): 40}
    opt = brute_force_optimum(chunks, ["L1", "L2"], prod, chg, 100)
    got = sum(a.qty + a.chg_from_prev_min for a in asg)  # rate 1.0
    assert got == opt  # 30+20+10 = 60, both on one line, A before B
    # ordering actually applied: the (sorted) first line carries no less
    load = {}
    for a in asg:
        load[a.line] = load.get(a.line, 0) + a.qty
    assert load.get("L1", 0) >= load.get("L2", 0)


def test_symmetry_breaking_respects_fixed_pins():
    f = sym_factory(["L1", "L2"])
    chunks = [("A", 30.0), ("B", 20.0)]
    # pin A to L2: ordering between pinned L2 and L1 must not make the
    # model infeasible or change the optimum
    asg, problems = solve_day_exact(f, chunks, 0, 100.0,
                                    time_limit_s=5.0,
                                    fixed={"A": "L2"})
    assert problems == []
    line_of = {a.sku: a.line for a in asg}
    assert line_of["A"] == "L2"
    prod = {"A": 30, "B": 20}
    chg = {("A", "B"): 10, ("B", "A"): 40}
    opt = brute_force_optimum(chunks, ["L1", "L2"], prod, chg, 100)
    # with A pinned to L2 the best is still 60 (B joins A on L2)
    got = sum(a.qty + a.chg_from_prev_min for a in asg)  # rate 1.0
    assert got == opt
