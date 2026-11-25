# Phase D coupled-cluster scaling (MEASURED, 2026-11-25, workspace box)

Clusters of N plants (seeds 101..1601, n_lines=4, n_skus=12, 7-day horizon,
supplier pools at 0.75x uncoupled usage = binding). Full data: the RESULT
JSON is reproduced below; regenerate with `python3 benchmarks/coupled_scaling.py`.

| plants | primal wall s | primal status | dual wall s | dual rounds |
|---|---|---|---|---|
| 2 | 3.613 | optimal | 4.518 | 20 |
| 4 | 10.003 | optimal | 13.855 | 20 |
| 8 | 62.865 | optimal | 24.93 | 20 |
| 16 | 240.084 | TIME LIMIT | 61.364 | 20 |

Findings (all measured):
- The ONE coupled MIP (HiGHS, 240 s limit) solves 2/4/8 plants to
  optimality (3.6/10.0/62.9 s) but hits the time limit at 16 plants:
  monolithic coupling stops scaling there on this class of instance.
- The decomposition (dual side) scales linearly with plants (4.5 ->
  61.4 s) because rounds x per-plant solves dominate; this is why the
  master-worker architecture is the path to larger coupled sizes.
- The repair-heuristic UB from the dual side is loose (heavy
  lateness after cuts); the Dantzig-Wolfe integer restricted master
  (coupled_dw.py) is the tighter UB path - measured separately in
  benchmarks/coupled_cg_scaling.py.
