"""Synthetic F&B plant generator with known-feasible ground truth (Stage 2).

Generates a factory at Makkook's published size — 17 lines, 96 slots,
4,001 SKUs (ROADMAP Stage 2 gate) — for the two-level rolling-horizon
solve, the ingestion pipeline and the back-test harness.

Interpretation of the published numbers (documented, not invented):
- 17 lines   -> 17 production-line resources at one location.
- 96 slots   -> 96 fifteen-minute scheduling slots per line-day
                (96 x 15 min = 24 h grid; the CP-SAT sequencing grid).
- 4,001 SKUs -> 4,001 finished-good items, long tail: only a fraction
                (default 25%) have demand in any given week.

F&B realism encoded: product families with sequence-dependent
changeovers (same class < cross-class < cross-family < allergen
washdown), line/family eligibility, per-family production rates,
1-3 raw materials consumed per SKU (purchased: no in-factory
producer), sparse long-tail demand split over 1-3 order lines.

Ground truth: demands are scaled to a target utilization and a greedy
campaign builder constructs an actual feasible plan; every generated
instance is therefore feasible BY CONSTRUCTION. verify_ground_truth
re-checks that independently from the records alone (never from
generator internals), per the honesty rules.

Determinism: one seeded random.Random drives everything; no set
iteration affects output order, so same seed -> byte-identical JSON.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from ..records.models import (Buffer, Calendar, Demand, Factory, Item,
                              Location, Operation, OperationMaterial,
                              OperationResource, Resource, SetupMatrix,
                              SetupRule)

FAMILIES = ("DAIRY", "BAKERY", "BEVERAGE", "SAUCE", "SNACK", "CONFECTION")
CLASSES_PER_FAMILY = 4
# Units per hour at nominal speed, per family (F&B packaging-line scale).
FAMILY_RATE_PER_HOUR = {"DAIRY": 2000, "BAKERY": 1200, "BEVERAGE": 3600,
                        "SAUCE": 1500, "SNACK": 1800, "CONFECTION": 900}
# Unit cost per SKU, per family (for KPI reporting, not solver input).
FAMILY_ITEM_COST = {"DAIRY": 1.20, "BAKERY": 0.80, "BEVERAGE": 0.50,
                    "SAUCE": 1.50, "SNACK": 1.10, "CONFECTION": 2.00}
# Changeover minutes. Same setup state -> 0 (SetupMatrix rule).
CROSS_CLASS_MIN = 30        # same family, different class
CROSS_FAMILY_MIN = 120      # different family: full washdown
ALLERGEN_MIN = 240          # either side an allergen class: certified wash
ALLERGEN_STATES = frozenset({"DAIRY-C0", "SNACK-C3"})  # milk, nuts
RAW_WASTE = 0.05            # raw material overconsumption factor


@dataclass(frozen=True)
class FnbParams:
    """Everything the generator needs; defaults are the gate size."""
    seed: int = 0
    n_lines: int = 17
    slots_per_day: int = 96
    slot_minutes: int = 15
    n_skus: int = 4001
    days: int = 7
    active_fraction: float = 0.25
    utilization: float = 0.65  # headroom for changeovers + shared lines
    horizon_start: datetime = datetime(2026, 11, 30)  # a Monday
    n_raw_materials: int = 30
    max_order_lines_per_sku: int = 3
    location: str = "PLANT-01"
    families: tuple = FAMILIES  # subset allowed for small test plants


@dataclass(frozen=True)
class Lot:
    """One ground-truth production lot: sku made on line during day."""
    line: str
    day: int            # 0-based day index from horizon_start
    sku: str
    qty: float
    state: str          # setup state (changeover class) of the SKU


@dataclass
class SyntheticPlant:
    """A generated factory plus the plan that proves it feasible."""
    factory: Factory
    params: FnbParams
    lots: list[Lot]

    @property
    def day_capacity_minutes(self) -> float:
        return self.params.slots_per_day * self.params.slot_minutes

    def save(self, path: str) -> None:
        payload = {
            "factory": json.loads(self.factory.model_dump_json()),
            "params": {**asdict(self.params),
                       "horizon_start": self.params.horizon_start.isoformat()},
            "lots": [asdict(lot) for lot in self.lots],
        }
        with open(path, "w") as fh:
            json.dump(payload, fh)

    @staticmethod
    def load(path: str) -> "SyntheticPlant":
        with open(path) as fh:
            payload = json.load(fh)
        p = dict(payload["params"])
        p["horizon_start"] = datetime.fromisoformat(p["horizon_start"])
        p["families"] = tuple(p["families"])
        return SyntheticPlant(Factory.model_validate(payload["factory"]),
                              FnbParams(**p),
                              [Lot(**lot) for lot in payload["lots"]])


def _state(family: str, cls: int) -> str:
    return f"{family}-C{cls}"


def _build_setup_matrix(families: tuple = FAMILIES) -> SetupMatrix:
    """All families x CLASSES states, all ordered pairs, F&B rules."""
    states = [_state(f, c) for f in families for c in range(CLASSES_PER_FAMILY)]
    rules = []
    for a in states:
        for b in states:
            if a == b:
                continue
            fam_a, fam_b = a.split("-")[0], b.split("-")[0]
            if a in ALLERGEN_STATES or b in ALLERGEN_STATES:
                minutes = ALLERGEN_MIN
            elif fam_a != fam_b:
                minutes = CROSS_FAMILY_MIN
            else:
                minutes = CROSS_CLASS_MIN
            rules.append(SetupRule(from_setup=a, to_setup=b,
                                   duration=timedelta(minutes=minutes)))
    return SetupMatrix(name="CHG-STD", rules=rules)


def _changeover_minutes(a: str, b: str) -> int:
    """Generator-side mirror of the matrix rules (construction only)."""
    if a == b:
        return 0
    if a in ALLERGEN_STATES or b in ALLERGEN_STATES:
        return ALLERGEN_MIN
    if a.split("-")[0] != b.split("-")[0]:
        return CROSS_FAMILY_MIN
    return CROSS_CLASS_MIN


def _line_families(n_lines: int, families: tuple = FAMILIES
                   ) -> list[tuple[str, ...]]:
    """Each line serves two adjacent families; every family gets lines
    (with fewer lines than 2 x families, coverage wraps the cycle)."""
    return [(families[i % len(families)], families[(i + 1) % len(families)])
            for i in range(n_lines)]


def generate_fnb_factory(params: FnbParams = FnbParams()) -> SyntheticPlant:
    """One seeded, feasible-by-construction F&B plant.

    Steps: structure (lines, families, SKUs, rates, eligibility) ->
    raw weekly demand -> scale to target utilization -> greedy campaign
    construction restricted to each SKU's due window. Raises
    RuntimeError if the greedy construction fails (increase retries via
    the seed loop in _generate_with_retries); the caller never sees a
    plant whose ground truth failed.
    """
    for attempt in range(20):
        try:
            return _generate_once(FnbParams(**{**params.__dict__,
                                               "seed": params.seed + attempt}))
        except RuntimeError:
            continue
    raise RuntimeError("greedy campaign construction failed 20 times; "
                       "lower utilization or widen eligibility")


def _generate_once(params: FnbParams) -> SyntheticPlant:
    rng = random.Random(params.seed)
    cap_min = params.slots_per_day * params.slot_minutes
    line_fams = _line_families(params.n_lines, params.families)
    family_lines: dict[str, list[str]] = {f: [] for f in params.families}
    for i, fams in enumerate(line_fams):
        for f in fams:
            family_lines[f].append(f"LINE-{i + 1:02d}")
    uncovered = [f for f in params.families if not family_lines[f]]
    if uncovered:
        raise RuntimeError(f"families with no eligible line: {uncovered}; "
                           "need n_lines >= len(families)")

    # --- SKUs: family, class, state, rate, eligible lines -----------
    skus = []
    for i in range(params.n_skus):
        family = params.families[i % len(params.families)]
        cls = rng.randrange(CLASSES_PER_FAMILY)
        state = _state(family, cls)
        rate_h = FAMILY_RATE_PER_HOUR[family] * rng.uniform(0.8, 1.2)
        # Eligible on every line of the family: random subsets localize
        # overload and break the nested-window packing argument.
        eligible = sorted(family_lines[family])
        skus.append({"name": f"SKU-{i:04d}", "family": family,
                     "state": state, "rate_min": rate_h / 60.0,
                     "eligible": eligible})

    # --- active set and raw weekly demand ----------------------------
    active = [s for s in skus if rng.random() < params.active_fraction]
    if not active:
        raise RuntimeError("empty active set")
    raw_qty = {s["name"]: rng.uniform(500, 5000) for s in active}
    rate_of = {s["name"]: s["rate_min"] for s in active}
    demand_minutes = sum(q / rate_of[name] for name, q in raw_qty.items())
    total_capacity = params.n_lines * params.days * cap_min
    scale = params.utilization * total_capacity / demand_minutes

    # --- split into order lines with due windows, round --------------
    # Due days skew late (max of two draws): the cumulative demand curve
    # stays under the linear cumulative capacity curve, which is what
    # makes the ground-truth construction feasible at 70% utilization.
    def due_day() -> int:
        return max(rng.randrange(params.days), rng.randrange(params.days))

    order_lines: dict[str, list[tuple[int, float]]] = {}  # sku -> [(due_day, qty)]
    for s in active:
        qty = max(10.0, round(raw_qty[s["name"]] * scale / 10.0) * 10.0)
        k = rng.randint(1, params.max_order_lines_per_sku)
        due_days = sorted(due_day() for _ in range(k))
        weights = [rng.uniform(0.5, 1.5) for _ in due_days]
        wsum = sum(weights)
        parts, acc = [], 0.0
        for j, w in enumerate(weights):
            part = qty - acc if j == len(weights) - 1 else \
                round(qty * w / wsum / 10.0) * 10.0
            parts.append(max(10.0, part))
            acc += parts[-1]
        order_lines[s["name"]] = list(zip(due_days, parts))

    # --- greedy campaign: lots split over line-days within due window
    load: dict[tuple[str, int], float] = {}
    seq: dict[tuple[str, int], list[Lot]] = {}
    lots: list[Lot] = []
    # Tightest due window first (and largest first inside a window):
    # nested prefix windows are packed safely in this order.
    ordered = sorted(active,
                     key=lambda s: (min(d for d, _ in order_lines[s["name"]]),
                                    s["name"]))
    for s in ordered:
        name = s["name"]
        remaining = sum(q for _, q in order_lines[name])
        first_due = min(d for d, _ in order_lines[name])
        blocked: set[tuple[str, int]] = set()
        while remaining > 1e-9:
            best = None
            for line in s["eligible"]:
                for day in range(first_due + 1):
                    key = (line, day)
                    if key in blocked:
                        continue
                    prev = seq[key][-1].state if key in seq else None
                    chg = _changeover_minutes(prev, s["state"]) if prev else 0
                    avail = cap_min - load.get(key, 0.0) - chg
                    if avail * s["rate_min"] < 10.0:  # no slivers
                        blocked.add(key)
                        continue
                    # Tight windows are placed first (outer sort); inside a
                    # window, spread to the least-loaded slot so lines shared
                    # by two families do not pile up on one day.
                    score = (load.get(key, 0.0) + chg, key)
                    if best is None or score < best[0]:
                        best = (score, key, chg, avail)
            if best is None:
                raise RuntimeError(f"no capacity for {name}")
            _, key, chg, avail = best
            # 0.02 min margin: records carry duration_per as a timedelta
            # (microsecond grid), the verifier recomputes from it.
            take = min(remaining, max(0.0, avail - 0.02) * s["rate_min"])
            lot = Lot(line=key[0], day=key[1], sku=name, qty=take,
                      state=s["state"])
            seq.setdefault(key, []).append(lot)
            lots.append(lot)
            load[key] = load.get(key, 0.0) + chg + take / s["rate_min"]
            remaining -= take

    # --- canonical records -------------------------------------------
    matrix = _build_setup_matrix(params.families)
    calendar = Calendar(name="24x7", default_value=1.0)
    locations = [Location(name=params.location, available_calendar="24x7")]
    raws = [Item(name=f"RAW-{i:02d}", description="purchased raw material")
            for i in range(params.n_raw_materials)]
    items = raws + [Item(name=s["name"], description=f"{s['family']} finished good",
                         cost=FAMILY_ITEM_COST[s["family"]]) for s in skus]
    resources = [Resource(name=f"LINE-{i + 1:02d}", location=params.location,
                          maximum=1.0, maximum_calendar="24x7",
                          setup_matrix="CHG-STD")
                 for i in range(params.n_lines)]
    operations = []
    for s in skus:
        n_raw = rng.randint(1, 3)
        mats = [OperationMaterial(item=s["name"], quantity=1.0)]
        for raw in rng.sample(range(params.n_raw_materials), n_raw):
            mats.append(OperationMaterial(
                item=f"RAW-{raw:02d}", quantity=-(1.0 + RAW_WASTE)))
        operations.append(Operation(
            name=f"MAKE-{s['name']}", item=s["name"], location=params.location,
            duration_per=timedelta(minutes=1.0 / s["rate_min"]),
            materials=mats,
            loads=[OperationResource(resource=line, quantity=1.0,
                                     setup=s["state"])
                   for line in s["eligible"]]))
    buffers = [Buffer(item=s["name"], location=params.location, onhand=0.0)
               for s in skus]
    demands = []
    for s in active:
        for j, (due_day, qty) in enumerate(order_lines[s["name"]]):
            demands.append(Demand(
                name=f"ORD-{s['name']}-{j}", item=s["name"],
                location=params.location,
                due=params.horizon_start + timedelta(days=due_day + 1),
                quantity=qty, priority=rng.randint(1, 3)))
    factory = Factory(locations=locations, items=items,
                      calendars=[calendar], setup_matrices=[matrix],
                      resources=resources, operations=operations,
                      buffers=buffers, demands=demands)
    plant = SyntheticPlant(factory=factory, params=params, lots=lots)
    problems = verify_ground_truth(plant)
    if problems:
        raise RuntimeError("ground truth failed verification: "
                           + "; ".join(problems[:5]))
    return plant


def verify_ground_truth(plant: SyntheticPlant) -> list[str]:
    """Independent feasibility check of the ground-truth campaign.

    Reads ONLY the canonical records and the lot list (never generator
    internals): per line-day, production minutes from operation rates
    plus sequence-dependent changeovers from the setup matrix must fit
    the slot grid; cumulative production before each demand's due must
    cover cumulative demand. Returns human-readable problems ([] = ok).
    """
    f = plant.factory
    problems: list[str] = []
    cap_min = plant.params.slots_per_day * plant.params.slot_minutes
    matrices = {m.name: m for m in f.setup_matrices}
    resources = {r.name: r for r in f.resources}
    sku_op: dict[str, Operation] = {}
    for op in f.operations:
        for m in op.materials:
            if m.quantity > 0:
                sku_op[m.item] = op
    # per line-day capacity with changeovers, in lot order
    by_ld: dict[tuple[str, int], list[Lot]] = {}
    for lot in plant.lots:
        by_ld.setdefault((lot.line, lot.day), []).append(lot)
    for (line, day), line_lots in sorted(by_ld.items()):
        res = resources.get(line)
        if res is None or res.setup_matrix not in matrices:
            problems.append(f"{line}: unknown resource or setup matrix")
            continue
        mtx = matrices[res.setup_matrix]
        total, prev = 0.0, None
        for lot in line_lots:
            op = sku_op.get(lot.sku)
            if op is None:
                problems.append(f"lot {lot.sku}: no producing operation")
                continue
            if not any(ld.resource == line for ld in op.loads):
                problems.append(f"lot {lot.sku} on ineligible line {line}")
            total += lot.qty * op.duration_per.total_seconds() / 60.0
            if prev is not None:
                chg = mtx.duration_between(prev, lot.state)
                if chg is None:
                    problems.append(f"{line} day {day}: no changeover rule "
                                    f"{prev} -> {lot.state}")
                else:
                    total += chg.total_seconds() / 60.0
            prev = lot.state
        # tolerance absorbs timedelta microsecond rounding of rates
        if total > cap_min + 0.05:
            problems.append(f"{line} day {day}: {total:.1f} min > {cap_min}")
    # demand coverage in due order
    dem_by_sku: dict[str, list[Demand]] = {}
    for d in f.demands:
        dem_by_sku.setdefault(d.item, []).append(d)
    lots_by_sku: dict[str, list[Lot]] = {}
    for lot in plant.lots:
        lots_by_sku.setdefault(lot.sku, []).append(lot)
    day_end = lambda d: plant.params.horizon_start + timedelta(days=d + 1)
    for sku, dems in dem_by_sku.items():
        produced = [(day_end(lot.day), lot.qty)
                    for lot in sorted(lots_by_sku.get(sku, []),
                                      key=lambda l: l.day)]
        cum_p, cum_d, pi = 0.0, 0.0, 0
        for dem in sorted(dems, key=lambda d: d.due):
            while pi < len(produced) and produced[pi][0] <= dem.due:
                cum_p += produced[pi][1]
                pi += 1
            cum_d += dem.quantity
            if cum_d > cum_p + 1e-6:
                problems.append(f"{sku}: demand {cum_d} by {dem.due} exceeds "
                                f"produced {cum_p}")
                break
    return problems
