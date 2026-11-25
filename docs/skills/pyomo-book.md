# Pyomo — Optimization Modeling in Python (3rd ed.)

> Distilled from Bynum, Hackebeil, Hart, Laird, Nicholson, Siirola, Watson, Woodruff, **Pyomo — Optimization Modeling in Python**, 3rd ed. (Springer, 2020). Open-access edition (Sandia report SAND2020-13991B), user-supplied PDF, born-digital text. Documents Pyomo 6.0. Feeds The-brain's modeling layer design and Stage 3 re-solve patterns.

## What Pyomo teaches The-brain (design lessons, not code)

- **Concrete models first** (3rd-ed. emphasis): build model objects directly in Python; data loading stays in Python, not in a DSL. The-brain's records -> compiler follows this: pydantic records, plain Python compilation.
- **Components**: Var (indexed over Sets), Param, Objective, Constraint (rule-based construction), Expression (named subexpressions), Suffix (solver-facing metadata). Indexed components + construction rules are the reusable-model pattern.
- **Blocks (ch. 8)**: hierarchical model composition - a block per time period / scenario, linked by constraints. This is how Stage 3 scenarios should be structured: one block per scenario, shared first-stage linking.
- **Sparse/"jagged" index sets** (9.4): build tuple sets of only valid combinations; never declare the full cross product and Skip. Directly applies to The-brain's compiler: only generate (operation, resource) pairs that exist in records.

## The lot-sizing anchor (sec. 8.6, Table 8.1)

ULS with backlogging: min sum_t (c y_t + h+ I+_t + h- I-_t), I_t = I_{t-1} + X_t - d_t, I_t = I+_t - I-_t, X_t <= P y_t.
Book data: c=4.6, I0+=5, I0-=0, h+=0.7, h-=1.2, P=5, d=[5,7,6.2,3.1,1.7].

Craft findings from converting it (all in tests):
- **Uncapacitated ULS-B has an exact O(n^3) DP** (interval decomposition extended with a terminal-backlog suffix option - the book's model charges end-of-horizon backlog once, which the naive interval DP misses; caught by cross-validation against CP-SAT).
- **Capacitated ULS-B with setups is NP-hard** - the book data (P=5, d_2=7) needs the CP-SAT path; `solve_uls_backlog` refuses honestly with NotImplementedError rather than silently relaxing.
- Integer scaling for CP-SAT: quantities x scale by S, per-unit costs by S, per-setup (dimensionless count) costs by S^2 - get the ratio wrong and setups become artificially cheap (caught by the independent HiGHS cross-check).

## Performance chapter (ch. 9) - the parts that matter

- **Persistent solvers** (9.3): keep the model+interface alive across re-solves; set_instance / add / remove constraint. Parameter sweep ran ~8x faster (0.91s vs 7.28s) than re-creating the model. Stage 3 local re-solve follows this pattern (with CP-SAT hints from the primer on top).
- Profile construction before optimizing (9.1); LinearExpression for bulk builds (9.2).

## Modeling extensions (Part III, awareness level)

- **GDP (ch. 11)**: disjuncts + logical constraints, solved via big-M or convex-hull transformation - the conceptual parent of our big-M idioms in `ilp/`.
- DAE (ch. 12), MPEC/complementarity (ch. 13), stochastic programming: noted for Stage 4 scale; not converted now.

## Code produced from this book

`packages/brain-core/brain_core/lotsizing/uls_backlog.py`: `solve_uls_backlog` (exact DP, uncapacitated) + `solve_uls_backlog_cpsat` (capacitated path, honest statuses, cost recomputed by `plan_cost`). Tests `tests/test_uls_backlog.py`: book Table 8.1 cross-validated against an independent scipy/HiGHS MIP, agreement with the Wolsey Wagner-Whitin DP when backlogging is priced out, 12-case randomized fuzz DP vs CP-SAT.

## License note

The open-access edition permits lawful use. No Pyomo code is copied; the skill captures modeling patterns and one formulation. Pyomo itself is BSD - usable as a dependency if ever needed.
