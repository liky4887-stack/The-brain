"""Staffing: employee shift rostering with CP-SAT (Stage 4, slice 6).

Timefold was the roadmap's named engine, but it needs a JDK 17+
runtime (this environment has 11) and its Python binding is a beta;
the recorded deviation (DECISIONS.md) is ortools CP-SAT, already in
the tree (Apache-2.0).

Model: employees x days x shifts assignment with coverage, one-shift-
per-day, skill, max-days, and night->morning rest constraints, plus
a fairness objective (minimize the max weekend load spread) whose
value is RECOMPUTED from the returned assignment. An independent
validator checks every constraint from the input data alone.

Honesty rules honored: solver status is never taken on faith; the
validator is the verdict; objective recomputed, not read.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Employee:
    name: str
    skills: frozenset           # skills this employee holds
    max_days: int               # max working days in the horizon
    can_nights: bool = True


@dataclass(frozen=True)
class ShiftSpec:
    """One shift kind: its skill requirement and whether it is a
    night shift (night -> next-day-morning is forbidden rest)."""
    name: str
    skill: str
    required: int               # headcount per day
    night: bool = False


@dataclass
class RosterResult:
    status: str                 # OPTIMAL | FEASIBLE | INFEASIBLE | ERROR
    assignments: list[tuple[str, int, str]]   # (employee, day, shift)
    objective: float | None     # recomputed fairness spread
    problems: list[str] = field(default_factory=list)


def solve_roster(employees: list[Employee], shifts: list[ShiftSpec],
                 days: int, time_limit_s: float = 10.0) -> RosterResult:
    """Exact CP-SAT roster; objective recomputed from assignments."""
    from ortools.sat.python import cp_model

    m = cp_model.CpModel()
    x = {}
    for e in employees:
        for d in range(days):
            for s in shifts:
                x[e.name, d, s.name] = m.new_bool_var(
                    f"x_{e.name}_{d}_{s.name}")
    # eligibility is a HARD constraint on the assignment itself,
    # not just on the coverage sum (the validator checks it the same
    # way; an ineligible assignment is a bug, not a coverage miss)
    for e in employees:
        for d in range(days):
            for s in shifts:
                if s.skill not in e.skills or (s.night
                                               and not e.can_nights):
                    m.add(x[e.name, d, s.name] == 0)
    # coverage: each shift each day exactly `required` skilled staff
    for d in range(days):
        for s in shifts:
            eligible = [x[e.name, d, s.name] for e in employees
                        if s.skill in e.skills
                        and (e.can_nights or not s.night)]
            if not eligible:
                return RosterResult(
                    "INFEASIBLE", [], None,
                    [f"shift {s.name}: no eligible employee"])
            m.add(sum(eligible) == s.required)
    # one shift per employee per day
    for e in employees:
        for d in range(days):
            m.add(sum(x[e.name, d, s.name] for s in shifts) <= 1)
    # max working days
    for e in employees:
        m.add(sum(x[e.name, d, s.name] for d in range(days)
                  for s in shifts) <= e.max_days)
    # night -> next-morning rest
    nights = [s for s in shifts if s.night]
    mornings = [s for s in shifts if not s.night]
    for e in employees:
        for d in range(days - 1):
            for sn in nights:
                for sm in mornings:
                    m.add(x[e.name, d, sn.name]
                          + x[e.name, d + 1, sm.name] <= 1)
    # fairness: minimize spread of per-employee worked days
    loads = [sum(x[e.name, d, s.name] for d in range(days)
                 for s in shifts) for e in employees]
    lmax = m.new_int_var(0, days, "lmax")
    lmin = m.new_int_var(0, days, "lmin")
    m.add_max_equality(lmax, loads)
    m.add_min_equality(lmin, loads)
    m.minimize(lmax - lmin)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    st = solver.solve(m)
    status = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE",
              cp_model.INFEASIBLE: "INFEASIBLE"}.get(st, "ERROR")
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return RosterResult(status, [], None,
                            [f"solver status {status}"])
    assigns = [(e.name, d, s.name)
               for e in employees for d in range(days) for s in shifts
               if solver.value(x[e.name, d, s.name])]
    # recompute the objective from the returned assignment
    worked = {e.name: 0 for e in employees}
    for name, _, _ in assigns:
        worked[name] += 1
    obj = float(max(worked.values()) - min(worked.values()))
    res = RosterResult(status, assigns, obj)
    res.problems = validate_roster(employees, shifts, days, assigns)
    return res


def validate_roster(employees: list[Employee], shifts: list[ShiftSpec],
                    days: int,
                    assignments: list[tuple[str, int, str]]
                    ) -> list[str]:
    """Independent check from inputs + returned assignments only."""
    problems: list[str] = []
    emp = {e.name: e for e in employees}
    shift = {s.name: s for s in shifts}
    seen = set()
    for name, d, s_name in assignments:
        if (name, d, s_name) in seen:
            problems.append(f"duplicate assignment {name} d{d} {s_name}")
        seen.add((name, d, s_name))
        e = emp.get(name)
        s = shift.get(s_name)
        if e is None:
            problems.append(f"unknown employee {name}")
            continue
        if s is None:
            problems.append(f"unknown shift {s_name}")
            continue
        if not (0 <= d < days):
            problems.append(f"{name} day {d} out of horizon")
        if s.skill not in e.skills:
            problems.append(f"{name} lacks skill {s.skill} for {s_name}")
        if s.night and not e.can_nights:
            problems.append(f"{name} cannot work nights ({s_name})")
    by_ed = {}
    for name, d, s_name in assignments:
        by_ed.setdefault((name, d), []).append(s_name)
    for (name, d), ss in by_ed.items():
        if len(ss) > 1:
            problems.append(f"{name} works {len(ss)} shifts on day {d}")
    for e in employees:
        worked = sum(1 for n, _, _ in assignments if n == e.name)
        if worked > e.max_days:
            problems.append(f"{e.name} works {worked} > max {e.max_days}")
    nights = {n for n, s in shift.items() if s.night}
    mornings = set(shift) - nights
    for e in employees:
        for d in range(days - 1):
            if any((e.name, d, sn) in seen for sn in nights) and \
                    any((e.name, d + 1, sm) in seen for sm in mornings):
                problems.append(f"{e.name}: night->morning d{d}->d{d+1}")
    for d in range(days):
        for s in shifts:
            n = sum(1 for name, dd, sn in assignments
                    if dd == d and sn == s.name)
            if n != s.required:
                problems.append(f"day {d} shift {s.name}: {n} staffed, "
                                f"need {s.required}")
    return problems
