# Principles of Constraint Programming (Apt)

> Distilled from Krzysztof R. Apt, **Principles of Constraint Programming** (Cambridge UP, 2003). User-supplied PDF; born-digital text, no OCR needed. Read with focus on ch. 3 (the CP framework), 6 (incomplete solvers / domain reduction), 7 (propagation algorithms), 8 (search). Feeds The-brain's propagation layer and Stage 3 explanations.

## The mental model (ch. 3)

Constraint programming = repeatedly **reduce the problem** (domain reduction / constraint propagation) until it is *Happy* (solved), *Atomic* (one variable left - split it), or *Proceed by Cases*. The loop: Preprocess -> propagate to fixpoint -> if not solved, split a domain and recurse. Everything in The-brain's `csp/` module is this loop made concrete.

## Domain reduction rules that matter (ch. 6.4)

For linear constraints on integer intervals, written in normal form
sum_POS a_i x_i - sum_NEG a_i x_i <= b (a_i > 0):

- **LINEAR INEQUALITY 1** (sec. 6.4.1): for j in POS, h'_j = min(h_j, floor(alpha_j)) with alpha_j = (b - sum_{POS-{j}} a_i l_i + sum_NEG a_i h_i)/a_j; for j in NEG, l'_j = max(l_j, ceil(beta_j)) with beta_j = (-b + sum_POS a_i l_i - sum_{NEG-{j}} a_i h_i)/a_j.
- **LINEAR EQUALITY** (sec. 6.4.2): an equality is two inequalities; apply both directions. Book example locked in tests: <3x - 5y = 4; x in [0..9], y in [1..8]> stabilizes at x in [3..8], y in [1..4] (Fig. 6.3-6.4).
- Single-variable equality collapses: x = b/a if a divides b and it lies in range, else FAILURE.
- **Bounds consistency** (sec. 6.4.7): the fixpoint of these rules computes the interval (bounds) consistency closure - what CP solvers call bounds propagation for linear constraints.
- Arithmetic constraints (6.5) extend the same idea to products via interval arithmetic; reals (6.6) add rounding discipline (outward rounding only).

## Search (ch. 8)

- **Labeling trees** and their reduced/prop variants: propagate-then-branch is always at least as good as branch-then-propagate.
- **Forward checking < partial look ahead < MAC** (maintaining arc/bounds consistency after every assignment). The-brain implements MAC on bounds (sec. 8.6.3).
- **Heuristics** (8.8): smallest-domain-first variable selection is the default that pays; value selection matters less for feasibility.
- **Branch and bound with constraint propagation** (8.7): add cost constraint obj < best at each node - the CP analogue of MIP bounding.
- **Backtrack-free search exists iff the CSP is strongly consistent enough** (8.5.1) - explains when propagation alone suffices.

## Consistency ladder (ch. 5)

Node < arc < hyper-arc < path < k-consistency; directional variants for ordered search. The practical ladder: bounds consistency on linear constraints (cheap, catches most) is The-brain's default; arc consistency on table-like constraints when needed.

## Code produced from this book

`packages/brain-core/brain_core/csp/bounds.py`: `LinearConstraint`, `propagate` (fixpoint of the rules above, exact Fraction arithmetic), `solve_mac`, `enumerate_solutions`. Tests `tests/test_csp_bounds.py`: book examples locked (Fig. 6.3-6.4, single-variable failures, SEND+MORE=MONEY unique solution 9567+1085=10652), 20 random systems cross-validated against brute-force enumeration.

## Where it feeds The-brain

- Stage 1/2: bounds propagation prunes the compiler's integer models before CP-SAT sees them.
- Stage 3: propagation traces are the raw material of plain-words explanations ("this order can't fit because line capacity forces x >= 12").
- Soundness note (Apt's discipline, adopted): propagation only *removes impossible values*, never guesses; the validator stays independent.
