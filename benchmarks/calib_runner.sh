#!/bin/bash
# calibB classes (lateness-free, setup calibrated by EOQ vs holding, min lot
# = one TBO): default HiGHS MIP solver (the only validated path), single
# thread, 600 s, gap 1e-4. Per size: 3 seeds x {plain, strengthened}
# under the same setup. Stop a class at the first size where seed 0 reaches
# 1% in neither variant. Every file carries status/nodes/gap/int check.
cd /workspaces/The-brain 2>/dev/null || cd ~/The-brain
for cls in calib3 calib1 calib5; do
  for n in 4 8 16 32 64 128; do
    any=0
    for seed in 0 1 2; do
      for st in none ls; do
        f=/tmp/cs-$cls-$n-s$seed-$st.json
        if ! { [ -f $f ] && jq -e .total_wall_s $f >/dev/null 2>&1; }; then
          MS_N=$n MS_CLASS=$cls MS_SEED=$seed MS_LIMIT=600 MS_CAP_SOLVE_S=60 MS_SOLVERS=highspy:1 \
            MS_REL_GAP=1e-4 MS_STRENGTH=$st MS_OUT=$f \
            PYTHONPATH=packages/brain-core python3 benchmarks/monolith_scaling.py \
            > /tmp/cs-$cls-$n-s$seed-$st.log 2>&1
        fi
        g=$(jq -r '.solves["highspy:1"].time_to_gap_s["1%"]' $f)
        [ $seed = 0 ] && [ "$g" != "null" ] && any=1
      done
    done
    [ $any = 0 ] && break
  done
done
touch /tmp/calib-ALL
