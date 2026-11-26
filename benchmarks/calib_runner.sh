#!/bin/bash
# calibrated lot-sizing classes: climb sizes per class until the monolith
# fails to reach 1% gap within 600 s (the real crossover). single-thread HiGHS.
cd ~/The-brain 2>/dev/null || cd /workspaces/The-brain
for cls in calib1 calib3 calib5; do
  for n in 4 8 16 32 64 128; do
    f=/tmp/cs-$cls-$n.json
    [ -f $f ] && jq -e .total_wall_s $f >/dev/null 2>&1 || \
      MS_N=$n MS_CLASS=$cls MS_LIMIT=600 MS_CAP_SOLVE_S=60 MS_SOLVERS=highspy:1 MS_REL_GAP=1e-4 MS_OUT=$f \
      PYTHONPATH=packages/brain-core python3 benchmarks/monolith_scaling.py > /tmp/cs-$cls-$n.log 2>&1
    g=$(jq -r '.solves["highspy:1"].time_to_gap_s["1%"]' $f)
    [ "$g" = "null" ] && break
  done
done
touch /tmp/calib-ALL
