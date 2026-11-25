# Wright — "Interior-Point Methods" (Simons Institute boot-camp slides, Aug 2017)

Distilled 2026-11-25 from the user's copy (50 Beamer pages, pdfTeX
digital, no OCR needed). Read twice. Stephen Wright's overview of the
theory behind primal-dual interior-point methods.

## Path-following algorithms for LP (implemented core matches Vanderbei)

- Newton's method applied to the perturbed KKT system F_sigma_mu; the
  central-path neighborhoods N2(gamma) = {(x,z,s) strictly feasible :
  ||XZe - mu e||_2 <= gamma mu}.
- Short-step algorithm SPF: full Newton steps with
  sigma = 1 - 0.4/sqrt(n), iterates stay in N2(0.4), complexity
  O(sqrt(n) log(1/eps)).
- Long-step LPF: wider neighborhood, smaller steps, O(n log(1/eps));
  better bound, slower in practice - "that's a theme": tighter theory
  tracks slower practical algorithms.
- Mizuno-Todd-Ye predictor-corrector (Algorithm PC): alternate
  predictor steps (sigma = 0, stop at the boundary of N2(0.5)) with
  corrector steps (sigma = 1, return to N2(0.25)); O(sqrt(n) log(1/eps)).
  Documented, NOT implemented: it needs a strictly feasible start in
  N2(0.25); our LP solver is infeasible-start (Vanderbei ch.17).
- Primal-dual potential reduction: Phi_rho(x,s) = rho ln(x^T s) -
  sum ln x_i s_i with rho > n balances centrality and gap reduction;
  step length chosen by minimizing Phi along the direction.

## Extensions (slides, all covered elsewhere in the repo)

- Convex QP and mixed monotone LCP: KKT of LP/QP are mixed monotone
  LCPs; algorithms carry over almost unchanged (see the Potra-Wright
  skill; QP implemented in brain_core.qp).
- Primal and dual barrier methods; self-concordant barrier theory
  (Nesterov-Nemirovskii): Newton on a self-concordant barrier has a
  domain of quadratic convergence; relationships between dual-barrier
  and primal-dual methods.

Use as the orientation map for the IPM literature; for algorithms
actually coded, cite Vanderbei (LP), Potra-Wright (QP), Gould et al.
(NLP).
