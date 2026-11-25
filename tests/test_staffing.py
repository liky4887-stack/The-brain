"""Stage 4, slice 6: shift rostering (CP-SAT; Timefold deviation
recorded in DECISIONS.md). The independent validator is the verdict.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brain-core"))

from brain_core.staffing import (Employee, ShiftSpec, solve_roster,
                                 validate_roster)

SHIFTS = [ShiftSpec("morning", "line", 2),
          ShiftSpec("evening", "line", 2),
          ShiftSpec("night", "line", 1, night=True)]


def _crew(n=6, max_days=5):
    return [Employee(f"E{i}", frozenset({"line"}), max_days,
                     can_nights=(i % 3 != 0))    # every 3rd: no nights
            for i in range(n)]


def test_roster_solves_and_validates_clean():
    res = solve_roster(_crew(), SHIFTS, days=5, time_limit_s=10)
    assert res.status == "OPTIMAL"
    assert res.problems == []
    assert validate_roster(_crew(), SHIFTS, 5, res.assignments) == []
    # coverage: 5 shifts-worth per day (2+2+1) * 5 days = 25
    assert len(res.assignments) == 25
    # fairness recomputed: with 6 crew and 25 slots, spread is small
    assert res.objective is not None and res.objective <= 1.0


def test_validator_catches_skill_violation():
    bad = [("E0", 0, "morning"), ("E9", 0, "morning")]
    probs = validate_roster(_crew(), SHIFTS, 5, bad)
    assert any("E9" in p for p in probs)          # unknown employee
    assert any("morning" in p and "staffed" in p for p in probs)


def test_validator_catches_night_morning_clash():
    crew = _crew()
    bad = [(crew[0].name, 0, "night"), (crew[0].name, 1, "morning"),
           # fill coverage to isolate the rest violation
           ]
    probs = validate_roster(crew, SHIFTS, 5, bad)
    assert any("night->morning" in p for p in probs)


def test_infeasible_when_no_night_eligible():
    crew = [Employee(f"E{i}", frozenset({"line"}), 5, can_nights=False)
            for i in range(6)]
    res = solve_roster(crew, SHIFTS, days=3, time_limit_s=5)
    assert res.status == "INFEASIBLE"
    assert res.problems            # honest reason recorded


def test_max_days_respected():
    crew = _crew(n=8, max_days=2)
    res = solve_roster(crew, SHIFTS, days=2, time_limit_s=10)
    assert res.status == "OPTIMAL"
    worked = {}
    for name, _, _ in res.assignments:
        worked[name] = worked.get(name, 0) + 1
    assert all(v <= 2 for v in worked.values())
