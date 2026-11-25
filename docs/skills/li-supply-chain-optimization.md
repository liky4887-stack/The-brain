# Skill: Optimization Modeling for Supply Chain Applications (Haitao Li)

Source: Haitao Li, "Optimization Modeling for Supply Chain Applications",
World Scientific, 469 pp. PDF received from the user 2026-11-25.
Read in two passes: (1) full TOC/structure, (2) deep read of the chapters
that govern The-brain's current and next stages: ch.2 (LP formulation
method), ch.3 (integer programming classics), ch.6 (constraint programming
for scheduling), ch.8 (production planning: LS-U/MPS/MRP/MRP II), ch.11
(machine scheduling formulations), plus structure-level review of ch.4
(network optimization), ch.7 (network design), ch.12 (RCPSP), ch.13-14
(TSP/VRP). Ch.5 (QUBO) and ch.15 (credit terms) noted as future/optional.

Where Williams is the general modeling discipline, Li is the supply-chain
application layer: concrete formulation families for exactly the problems
The-brain will meet at Stages 5+.

## 1. Formulation method (ch.2-3)

- LP assumptions to check before modeling: proportionality, additivity,
  divisibility, certainty, non-negativity. "Certainty" is the lie we tell
  with point forecasts - plan for sensitivity/robustness when demand
  sensing feeds the model.
- Steps: (0) define the problem conceptually with the domain expert,
  (1) decision variables, (2) objective, (3) constraints. Step 0 is where
  most real projects fail. Our Stage 0 spec-before-code rule is this.
- Integer-variable uses: indivisible quantities, 0-1 decisions, indicator
  links (x <= M*y) - same big-M discipline as Williams (realistic M).

## 2. Machine scheduling formulation families (ch.11) - THE core asset

The alpha|beta|gamma notation classifies problems (1|.|sum wjTj is our
engine core today; Pm, Fm, Jm, plus release dates rj, setups sij, no-wait
are the growth path). Five formulation families, each a different route
to the same optimum - which makes them cross-validation instruments:

- DISJUNCTIVE (11.2.1): y_ij = 1 if i before j; big-M pair
  s_i + p_i <= s_j + M(1-y_ij), s_j + p_j <= s_i + M*y_ij. Tardiness
  T_j >= s_j + p_j - d_j linearizes max{0, .} because minimization drives
  it tight. The most widely used approach; our CP-SAT interval/no_overlap
  model is its global-constraint descendant.
- POSITION-BASED (11.2.2): x_jk = job j at position k; one job per
  position, one position per job; completion of position k is cumulative
  processing; no idle time in an optimal 1||sum Tj schedule (holds for
  regular objectives incl. weighted tardiness WITHOUT release dates -
  the moment r_j exists, idleness can be optimal and position/cumulative
  formulations need care).
- LINEAR ORDERING (11.2.3): x_ij precedence booleans, x_ij + x_ji = 1,
  transitivity x_ij + x_jk + x_ki <= 2 (O(n^3) constraints), tardiness
  T_j >= sum_i p_i*x_ij + p_j - d_j - fully linear, no big-M, handles
  weighted tardiness cleanly. Implemented as our ordering_solver.
- TIME-INDEXED (11.3.3): x_jmt = starts at t; resource constraint sums
  all starts that would be active at t. Strong relaxations, but variables
  scale with the horizon - wrong choice for long-horizon fine-grained time.
- ROUTING-BASED (11.3.4): parallel-machine scheduling IS a CVRP
  (machines = vehicles, jobs = nodes, makespan = capacity). When The-brain
  grows to distribution, scheduling and routing share one formulation
  vocabulary (ch.13-14).

Parallel machines (11.3): assignment z_jm + sequencing x_ij + "same
machine" y_ij with z_im + z_jm + y_ij <= 2. IDENTICAL machines mean
symmetry - Williams' warning applies; order or aggregate.

Shop scheduling (11.4): flow shop = precedence chains between stages
(S_jk >= S_j,k-1 + p_j,k-1) + disjunctive no-overlap per machine; job
shop = same but per-job routes; flexible variants add machine choice.
This is the exact shape of The-brain's multi-stage future: precedence
constraints + one no-overlap per machine.

## 3. CP for scheduling (ch.6)

- CP = declarative + global constraints + propagation/search; scheduling
  is where CP beats MIP in practice. Confirms CP-SAT as our scheduler.
- Temporal modeling: start-start lags S_j >= S_i + delta_ij; precedence is
  the special case delta = p_i. Covers overlapping activities without new
  machinery.
- JIT/earliness-tardiness (6.3.1): penalize BOTH earliness and lateness
  (material pressure vs delay): min sum e_i*E_i + l_i*L_i with
  E_i >= a_i - t_i, L_i >= t_i + p_i - d_i. This is the natural next
  objective after weighted tardiness - note earliness makes idleness
  potentially optimal again (non-regular objective).
- Job shop via CP: interval variables + NoOverlap per machine + precedence
  - the model stays tiny where MIP explodes.

## 4. Production planning ladder (ch.8) - the Stage 5+ demand side

- LS-U (single-item uncapacitated lot sizing): produce x_t, setup y_t,
  inventory I_t; balance I_{t-1} + x_t = d_t + I_t; x_t <= M*y_t (M =
  remaining demand, the realistic bound); setup + variable + holding costs.
- MPS: multi-product LS-U + shared resource capacity
  sum_i(a_ik*x_it + b_ik*y_it) <= L_kt. The capacity constraint is what
  couples products - without it the model decomposes per product.
- MRP: BOM explosion - demand dependencies r_ij, lead times, minimum lot
  sizes; backward iteration from end-product demand. JIT logic: arrive
  when needed, not before.
- MRP II = MRP + explicit resource capacities. The-brain's planning
  hierarchy: forecast -> MPS (lot sizing) -> MRP II (capacity-feasible
  materials) -> scheduling (our engine core). Do not skip levels.

## 5. Network view (ch.4, 7, 12-14) - structure reviewed, deep-read later

- Network flow models: flow conservation at nodes; transportation,
  transshipment, shortest path, max flow, assignment are all min-cost
  flow special cases - and totally unimodular (Williams), so LP solves
  them to integrality. Route these to HiGHS, never to a brute IP.
- Facility location (p-median, uncapacitated/capacitated FLP, fixed-charge
  network design, hub location): the strategic layer; Stage 5+ territory.
- RCPSP (ch.12): scheduling + renewable resource capacities; time-indexed
  and disjunctive formulations; multi-mode = machine choice per activity.
  CP-SAT's cumulative constraint is the native fit.
- TSP/VRP (ch.13-14): subtour elimination, MTZ, flow-based formulations;
  time windows; periodic VRP; technician routing. The distribution future.

## 6. Rules now encoded in brain_core

- solvers/ordering_solver.py: Li's linear-ordering formulation (11.2.3)
  generalized to weighted tardiness with optional hard deadlines, as an
  independent second solver. tests/test_ordering_solver.py cross-validates
  it against the interval solver AND the exhaustive baseline on every
  example and golden scenario: three independent routes, one optimum.
  This is Williams' validation philosophy mechanized.
- Objective notes: earliness-tardiness (JIT) and multi-machine support are
  the documented next extensions; the formulation to use for each is cited
  above, not improvised.

## Open threads

- Ch.5 QUBO: quantum-annealing formulations; watch-only, no code need.
- Ch.10 SC configuration (safety stock, food supply chain with loss and
  quality) becomes relevant for the user's F&B vertical - deep-read 10.4
  when that stage opens.
- Ch.13-14 routing: deep-read when distribution enters scope.
- Appendices cover CPLEX OPL and solving methods; useful syntax reference
  only.
