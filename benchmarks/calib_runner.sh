#!/bin/bash
# calibrated lot-sizing classes, IPM+crossover solver (new monolith default,
# review 9:37 PM), single-thread HiGHS, 600 s, gap 1e-4. For each size run
# plain and strengthened ((l,S) prefix cuts, probe only); stop a class at the
# first size where NEITHER reaches 1% gap in 600 s.
cd /workspaces/The-brain 2>/dev/null || cd ~/The-brain
for cls in calib3 calib1 calib5; do
  for n in 4 8 16 32 64 128; do
    any=0
    for st in none ls; do
      f=/tmp/cs-$cls-$n-$st.json
      if ! { [ -f $f ] && jq -e .total_wall_s $f >/dev/null 2>&1; }; then
        MS_N=$n MS_CLASS=$cls MS_LIMIT=600 MS_CAP_SOLVE_S=60 MS_SOLVERS=highspy:1 \
          MS_REL_GAP=1e-4 MS_HIGHS_OPTS=solver=ipm MS_STRENGTH=$st MS_OUT=$f \
          PYTHONPATH=packages/brain-core python3 benchmarks/monolith_scaling.py \
          > /tmp/cs-$cls-$n-$st.log 2>&1
      fi
      g=$(jq -r '.solves["highspy:1"].time_to_gap_s["1%"]' $f)
      [ "$g" != "null" ] && any=1
    done
    [ $any = 0 ] && break
  done
done
touch /tmp/calib-ALL
