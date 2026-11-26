#!/usr/bin/env bash
# Root-LP algorithm experiment on hard n=128 (review 16 item 1): same
# instance (caps cached after the first run), HiGHS options varied.
cd "$(dirname "$0")/.."
for opt in "solver=choose" "solver=ipm" "solver=ipm,run_crossover=off" "solver=simplex" "solver=ipm,run_crossover=on"; do
  tag=$(echo "$opt" | tr ',=' '__')
  MS_N=128 MS_CLASS=hard MS_LIMIT=600 MS_CAP_SOLVE_S=2 MS_SOLVERS="highspy:1" MS_HIGHS_OPTS="$opt" MS_OUT=/tmp/exp-hard128-$tag.json PYTHONPATH=packages/brain-core \
    python benchmarks/monolith_scaling.py > /tmp/exp-$tag.log 2>&1
  echo "$opt rc=$?" >> /tmp/exp-done.txt
done
echo ALL > /tmp/exp-ALL
