# Ahuja, Magnanti & Orlin — Network Flows: Theory, Algorithms, and Applications (Prentice Hall 1993)

Distilled 2026-11-25 from the user's full copy (863 pages). This is a
SCANNED book with an OCR text layer (CVISION producer; visible OCR noise
in prose and formulas). Per the user's OCR gate, both algorithm pages
relied on (Figure 6.17 labeling algorithm, Figure 9.9 successive shortest
path, plus Theorems 6.3-6.5 and Lemmas 9.11-9.12) were verified against
the rendered page images before use. Read in two passes: structure from
contents, then deep read of ch.6.5 (labeling algorithm and max-flow
min-cut) and ch.9.7 (successive shortest path) with ch.9.1-9.6 framing.

## Maximum flows (ch.6, implemented)

- Residual network G(x): arc (i,j) has residual capacity
  r_ij = (u_ij - x_ij) + x_ji.
- Labeling algorithm (Figure 6.17): repeatedly find an s-t augmenting
  path in G(x) (BFS = Edmonds-Karp variant), augment
  delta = min r_ij along it, stop when the sink cannot be labeled.
- Theorem 6.3 (max-flow min-cut): max flow value = min s-t cut capacity.
  The algorithm terminates with both: the labeled set S defines the cut.
- Theorem 6.4 (augmenting path): x* is maximum iff G(x*) has no
  augmenting path.
- Theorem 6.5 (integrality): integer capacities => an integer max flow
  exists (the labeling algorithm produces one). Does NOT mean every
  optimal flow is integer.

## Minimum cost flows (ch.9, implemented with an explicit scope limit)

- Pseudoflows and imbalances e(i) = b(i) + inflow - outflow; excess
  (e>0) vs deficit (e<0) nodes.
- Reduced-cost optimality (Theorem 9.3): x* optimal iff some potentials
  pi make every reduced cost c^pi_ij = c_ij - pi(i) + pi(j) >= 0 in G(x).
- Successive shortest path (Figure 9.9): start x = 0, pi = 0; while an
  excess node k exists, take shortest path distances d from k over
  reduced costs, pick a deficit node l, update pi := pi - d, augment
  delta = min(e(k), -e(l), min r_ij on P). Lemmas 9.11-9.12: augmenting
  along a shortest path preserves reduced-cost optimality.
- Scope limit (stated in the book's ch.9 assumptions: "all arc costs are
  nonnegative"): pi = 0 must already satisfy reduced-cost optimality.
  Negative-cost instances need cycle-canceling (sec. 9.6) first - NOT
  implemented. The implementation REJECTS negative costs loudly; during
  testing, the LP cross-check caught exactly this silent-wrong-answer
  case (a negative cycle beats any s-t path flow).
- Cycle-canceling (sec. 9.6, documented not implemented): while the
  residual network has a negative-cost directed cycle, augment around it.

## Rest of the book (structure read, not deep-read - do not cite details)

Ch.1-5 foundations (graphs, complexity, shortest paths: Dijkstra,
label-correcting, all-pairs); ch.6.6+ max-flow algorithms beyond
labeling (preflow-push, capacity scaling); ch.7-8 assignments,
matchings, spanning trees; ch.9 other min-cost-flow algorithms
(capacity scaling, network simplex); ch.10-11 generalized and convex
flows; ch.12-19 applications and special topics ( Lagrangian relaxation
on networks, multicommodity, network design).

## Cross-book synthesis

Network flow is the polyhedral sweet spot every other book points at:
Bertsimas & Tsitsiklis ch.7 (network simplex, total unimodularity),
Wolsey ch.3 (well-solved problems), Hillier ch.9, Li's supply-chain
formulations. The-brain now has the two flagship algorithms, with the
max-flow/min-cut theorem itself as the test oracle (brute-force cuts)
and the in-house simplex as an independent oracle for min-cost flow.

## Code

packages/brain-core/brain_core/network/flows.py: max_flow (labeling /
Edmonds-Karp) and min_cost_flow (SSP with potentials, Bellman-Ford
distances). Explicit residual edge pairs per original arc, so
antiparallel real arcs never alias. tests/test_flows.py: max flow equals
brute-force min cut on 100 random graphs (plus feasibility and
integrality); min cost flow matches the simplex LP solver on random
instances (plus capacity/balance feasibility, unreachable-demand and
negative-cost rejection, and a hand-computed example).
