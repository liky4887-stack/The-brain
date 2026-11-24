# Golden scenarios

Regression anchors for the engine core: realistic instances with locked
expected outcomes in `data/scenarios/goldens.json`, enforced by
`tests/test_golden.py`.

## Lock strengths (kept honest)

- `proof: "exhaustive"` - at test time we enumerate every order sequence and
  confirm the locked objective is the true optimum. The solver must match it.
  Used for all scenarios up to 8 orders (40,320 sequences).
- `proof: "solver"` - the locked value is the solver's own proven-optimal
  result. Above ~10 orders exhaustive enumeration is impractical at test time
  (14 orders = 87 billion sequences), so the lock guards against regressions
  but is not an independent optimality proof. Labeled as such.

A 20-order variant was tried and dropped: CP-SAT could not prove optimality
within 110 seconds, and locking an unproven value would dress up a guess as a
golden. `shift_14` (14 orders, proven optimal in ~11 s) sits at the honest
edge of what we can lock.

## The scenarios

| file | what it exercises | locked objective |
| --- | --- | --- |
| factory_day_a | mixed day, 8 orders, varied weights and due dates | 4.0 |
| factory_day_b | tight middle of the day forces weighted trade-offs | 78.0 |
| clear_day | every due date at end of day; objective 0 must be found | 0.0 |
| dominant_weight | one order outweighs the rest 50-100x; it must never be late | 51.0 |
| shift_14 | one full shift, 14 orders, beyond exhaustive reach | 190.0 |

Every returned plan is also checked by the independent validator
(`validation/validator.py`), and `test_every_scenario_file_is_locked` fails
the suite if a scenario file ever appears without a golden lock.

## Rule for adding scenarios

New realistic instances go in `data/scenarios/` with a goldens entry. If the
order count is within exhaustive reach, use `proof: "exhaustive"`. Above it,
lock only a solver-proven optimal value and mark `proof: "solver"`. Never lock
a value the solver has not proven.
