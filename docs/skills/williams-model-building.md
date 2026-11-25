# Skill: Model Building in Mathematical Programming (Williams, 5th ed.)

Source: H. Paul Williams, "Model Building in Mathematical Programming", 5th
edition, Wiley 2013, 433 pp. PDF received from the user 2026-11-25.
Read in two passes: (1) full structure + all chapter maps, (2) deep read of the
chapters that govern how The-brain builds models: ch.2 (solving + constraint
programming), ch.3 (building LP models), ch.6 (validating a model), ch.9
(building IP models I), ch.10 (building IP models II, incl. symmetry and
"when to use IP"). Parts II/III are worked examples of the same principles
(food manufacture, factory planning, manpower, refinery, ...); their structure
was reviewed, principles below cover them.

This is the modeling-discipline reference for The-brain's optimization layer.
Apply it whenever a constraint, objective, or variable is added to any model.

## 1. Objectives (ch.3.2)

- Only variable (marginal) costs and profit contributions belong in an
  objective. Fixed costs enter only through 0-1 decision variables (see fixed
  charge). Using average costs is a classic modeling error.
- Cost-minimization with fixed demands vs profit-maximization with variable
  demand are different models. Start with the simpler one; extend only when
  the first is accepted.
- Multiple/conflicting objectives: (a) solve with each in turn, (b) convert
  all but one to constraints and vary right-hand sides, (c) weighted composite.
  There is no cut-and-dried answer; present alternatives as policy options.
  The-brain: this is the "explainable objective trade-offs" the blueprint asks
  for at Stage 5.
- Minimax objective `min max_i(expr_i)`: introduce z, add `expr_i - z <= 0`
  for all i, minimize z. Exact LP, no approximation. (Our CP-SAT tardiness
  linearization is the same device.)
- No real objective? Optimize a contrived one anyway: extreme solutions
  stress the constraints and are a validation tool (see §4).

## 2. Constraints (ch.3.3)

- Standard taxonomy: capacity, raw-material, demand limits, material balance
  (continuity: in = out, easily forgotten -> classic cause of unboundedness),
  quality/blending.
- HARD vs SOFT: a constraint that can be violated at a price gets deviation
  variables: `a.x - u <= b` (or `a.x + u - v = b` for equalities) with u,v
  penalized in the objective. Our due_date (soft, tardiness penalized) vs
  deadline (hard) split is exactly this. Williams: at most one of u,v is
  positive at optimality.
- Conflicting constraints -> goal programming: every constraint becomes a
  goal with weighted deviation variables; minimize total (or max) deviation.
- Keep redundant constraints that may bind under future data; their shadow
  prices carry information. Do not strip a constraint just because it is
  slack today.
- Simple bounds `x <= U` and GUB-type sums are handled specially by solvers;
  prefer expressing them as bounds.

## 3. Good models (ch.3.4) and scale (ch.3.4.5)

- Optimize for: understandability, error-detection, then solution speed, in
  that order of daily importance. Prefer explicit variables over substituted
  compact forms; use mnemonic names (we do: start_O1 etc.).
- UNITS: keep all non-zero coefficients within ~0.1..10. Widely disparate
  magnitudes make models numerically hard. This is why brain-core scales
  weights by WEIGHT_SCALE=1000 rather than mixing floats into integer
  coefficients, and why big-M values must be realistic (§5).

## 4. Validating a model (ch.6.1) - the two-way process

- Three outcomes: infeasible / unbounded / solvable. All three are
  diagnostics, not just failures.
- Infeasible: take a KNOWN feasible plan (last week's schedule) and
  substitute it into the constraints; every constraint it violates was modeled
  too restrictively. Infeasibility is usually a mutual incompatibility, not
  one bad row - do not blame a single constraint.
- Unbounded: a missing physical constraint, most often a forgotten material
  balance. Give every variable a large finite upper bound; any variable that
  finishes at its bound is the suspect.
- Solvable but suspicious: compare the objective to known practice. Better
  than reality -> under-constrained (present the plan and ask planners why it
  is impossible). Worse -> over-constrained (substitute the known plan).
- Error-detection formulations: soften a risky constraint with a highly
  penalized violation variable; if it appears in the solution, the original
  constraint was wrong.
- Build-validate-rebuild is iterative; the understanding gained is worth more
  than any single solution. Matches our independent-validator design.

## 5. Integer modeling patterns (ch.9) - the reusable toolbox

Conventions: delta = 0-1 variable, M = upper bound, m = lower bound,
eps = tolerance (1 if all data integer).

- INDICATOR LINK: `x > 0 -> delta = 1` is `x - M*delta <= 0`. The reverse
  (`delta = 1 -> x > 0`) needs a threshold: `x - m*delta >= 0`. The reverse
  is often unnecessary because optimality enforces it (fixed charge) - do not
  add constraints the objective already guarantees.
- FIXED CHARGE: cost = c1*x + c2*delta with `x - M*delta <= 0`.
- CONSTRAINT ON/OFF: `delta=1 -> a.x <= b` is `a.x + M*delta <= M + b`,
  M = upper bound of (a.x - b). Reverse implication needs eps and the lower
  bound m: `a.x - (m - eps)*delta >= b + eps`.
- LOGICAL CONDITIONS: or: `d1 + d2 >= 1`; implication: `d1 - d2 <= 0`;
  iff: `d1 - d2 = 0`. Use Boolean identities (De Morgan etc.) to normalize
  first, then translate. Easy to get wrong without the algebra - always
  verify by substituting 0/1.
- DISJUNCTIVE (either/or) constraints: indicator per alternative +
  `d1 + ... + dN >= 1`. "At least / at most k of N hold": same with `>= k`
  (and the reverse-implication form for at-most). Machine no-overlap is the
  two-alternative case; CP-SAT's AddNoOverlap is the global-constraint form.
- PRODUCTS: linearize d1*d2 -> d3 with `d3<=d1, d3<=d2, d3>=d1+d2-1`.
  x*delta (continuous x) -> y with `y<=M*delta, y<=x, y>=x-M*(1-delta)`.
- SOS1 (exactly one nonzero: depot siting, discrete capacity) and SOS2
  (adjacent pair: piecewise-linear functions, economies of scale). Prefer
  solver-native SOS support over manual binaries.
- SEQUENTIALLY DEPENDENT decisions across periods: chain constraints
  (`-2g_t + g_{t+1} <= 0` pattern for ordered states).

## 6. Good vs bad IP formulations (ch.10) - why models solve slowly

- The LP relaxation's strength, not the variable/constraint count, drives
  solve time. A bigger model with a tighter relaxation is FASTER.
- DISAGGREGATE: `d1 + ... + dn - n*d <= 0` is weak; the n constraints
  `di - d <= 0` are strictly tighter (same integer solutions, smaller LP
  region). Same for shared big-M: `x1 + ... + xn <= M*d` -> per-variable
  `xi <= Mi*d`. Default to the disaggregated form.
- Make M as realistic as possible: oversize M weakens the relaxation and can
  produce spurious "integer" solutions inside integrality tolerance.
- Tighten integer variable bounds through constraint propagation (presolve);
  fixing even a few variables can collapse the tree.
- SYMMETRY is a computational disease in IP: identical machines/vehicles/
  workers create exponentially many equivalent solutions. Break it: ordering
  constraints (`d1j >= d2j >= ...`) or aggregate to count variables
  (`n_j = number assigned`) when the relaxation stays tight. The-brain has
  one machine today; the moment machines become identical parallel machines,
  symmetry breaking is mandatory.
- Total unimodularity (transportation/assignment/network flows): LP solves
  these to integer optimality for free. Recognize the structure (0/±1
  coefficients, <=2 per column) and route to LP, not IP. Feeds the solver
  router: network-shaped problems -> HiGHS LP, no integrality needed.
- No shadow prices in IP: the duality gap measures how meaningless they are.
  Sensitivity analysis in IP = re-solve with perturbed data.
- BEFORE building big: build the small version, experiment, reformulate,
  then scale. (Exactly our Stage 0-4 path. Our shift_14 golden is the small
  version; the dropped shift_20 is the signal to reformulate before scaling.)
- If IP is still too hard after reformulation: heuristic for a good incumbent,
  then use it as a bound/cut-off. Never present a heuristic solution as
  optimal (our honest-status rule).

## 7. CP vs IP (ch.2.4)

- CP strengths: global constraints (all_different, cumulative, circuit,
  element), domain propagation, better for "needle in a haystack"
  feasibility and highly combinatorial models. IP strengths: relaxation
  bounds that prove optimality. CP "usually lacks the ability to prove
  optimality" (except by iterated bounds) - consistent with our CP-SAT
  experience: fast to a good plan, slow to prove (shift_20 unproven at 110s).
- Modern CP-SAT is a hybrid (LP-style bounds + propagation), which blurs
  this, but the routing rule stands: scheduling/sequencing -> CP-SAT;
  linear cost/allocation/network -> HiGHS LP/MIP. Matches the user's
  decision in his notes.
- Use solver-native global constraints where they exist instead of
  hand-built big-M encodings; they propagate far better.

## 8. Rules now encoded in brain_core/modeling/patterns.py

indicator_link, fixed_charge, soft_constraint, at_least_k/at_most_k,
disjunction, minimax, disaggregate, symmetry_break_order - each with the
realistic-M rule and brute-force-verified semantics. Cite this skill when
using them.

## Open threads

- Part II/III worked examples (food manufacture, factory planning) are the
  templates for the multi-period, multi-product Stage 5+ models; re-read
  13.1-13.4 when those stages start.
- Chance constraints (3.3.7) and stochastic programs (4.2) become relevant
  when demand sensing (Nixtla/Prophet) feeds the optimizer - deterministic
  equivalent b' for now.
- Column generation (9.6) and decomposition (4.3) are the scale-out routes
  if shift-scale instances outgrow monolithic CP-SAT.
