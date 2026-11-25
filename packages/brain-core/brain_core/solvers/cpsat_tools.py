"""CP-SAT tooling from the CP-SAT Primer (Krupke et al., CC-BY 4.0).

Source: Krupke, "The CP-SAT Primer: Using and Understanding Google
OR-Tools' CP-SAT Solver" (github.com/d-krupke/cpsat-primer), chapters
Parameters (hints, assumptions, unsat cores) and Coding Patterns
(warm starts). Three mechanics The-brain's later stages need:

- solution hints / warm starts (add_hint): seed the search with a
  known-good solution; Stage 3's local re-solve uses this.
- assumptions + only_enforce_if + sufficient_assumptions_for_
  infeasibility: name the constraints responsible for an infeasible
  model; Stage 3's plain-words explanations use this.
- the solver is stateless: no learned clauses carry over between
  solves, so every helper here re-solves from scratch.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from ortools.sat.python import cp_model


def solve_with_hint(model: cp_model.CpModel,
                    hint: Mapping[cp_model.IntVar, int],
                    time_limit_s: float = 30.0) -> dict:
    """Solve with a (possibly partial) solution hint. The hint seeds
    the search but never constrains it: a wrong hint costs time, never
    correctness. Returns status, and values for the hinted variables
    (empty when the model has no solution)."""
    for var, value in hint.items():
        model.add_hint(var, value)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.solve(model)
    name = solver.status_name(status)
    values = ({v: solver.value(v) for v in hint}
              if name in ("OPTIMAL", "FEASIBLE") else {})
    objective = (solver.objective_value
                 if name in ("OPTIMAL", "FEASIBLE") and model.has_objective()
                 else None)
    return {"status": name, "values": values, "objective": objective}


def assert_hint_feasible(model: cp_model.CpModel,
                         hint: Mapping[cp_model.IntVar, int],
                         time_limit_s: float = 30.0) -> bool:
    """The primer's check: temporarily FIX the hinted variables and
    test feasibility. Works on a clone so the caller's model is
    untouched. True iff the hint is a feasible partial assignment."""
    clone = model.clone()
    indicators = []
    for var, value in hint.items():
        ind = clone.new_bool_var(f"hintfix_{var.name}")
        clone.add(var == value).only_enforce_if(ind)
        indicators.append(ind)
    clone.add_assumptions(indicators)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    return solver.solve(clone) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def explain_infeasibility(model: cp_model.CpModel,
                          named_constraints: Sequence[tuple],  # (name, ct)
                          time_limit_s: float = 30.0) -> dict:
    """Name the constraints behind an infeasible model.

    named_constraints: (name, bounded-expression) pairs; each is added
    to a fresh model guarded by an indicator bool via only_enforce_if,
    and all indicators are assumed true. If the model is infeasible,
    sufficient_assumptions_for_infeasibility returns the names of a
    sufficient conflicting subset (the primer's unsat-core example:
    x+y<=4, x+z<=2, z>=4 points at the last two).

    Caveats from the primer: only reifiable constraints can be guarded
    this way (pass lower-level linear constraints here), and bounded
    expressions are bound to their model, so we work on a clone of the
    model the expressions came from.
    """
    model = model.clone()
    indicators = []
    for name, ct in named_constraints:
        ind = model.new_bool_var(name)
        model.add(ct).only_enforce_if(ind)
        indicators.append(ind)
    model.add_assumptions(indicators)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.solve(model)
    name = solver.status_name(status)
    core = None
    if status == cp_model.INFEASIBLE:
        # the solver's sufficient set is a pointer, not a full or
        # minimal core; refine it into a minimal infeasible subset by
        # deletion filtering (the primer's verification mindset)
        core = _minimal_core(model, indicators, time_limit_s)
    return {"status": name, "core": core}


def _minimal_core(model, indicators, time_limit_s):
    """Smallest-by-deletion conflicting subset, found by toggling
    assumptions on the one model (bounded expressions are bound to
    their model and cannot be replayed into another)."""
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    active = list(range(len(indicators)))
    i = 0
    while i < len(active):
        trial = active[:i] + active[i + 1:]
        model.clear_assumptions()
        model.add_assumptions([indicators[k] for k in trial])
        if solver.solve(model) == cp_model.INFEASIBLE:
            active = trial
        else:
            i += 1
    return [indicators[k].name for k in active]
