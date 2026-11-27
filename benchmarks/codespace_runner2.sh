#!/usr/bin/env bash
# Phase 1: sizes <= 256 run 3 in parallel (threads=1, explicit); phase 2:
# 512 and 1024 run ALONE (memory/timing). Results go to $BRAIN_RUNS_DIR (default ~/brain-runs)
# (copied off by the supervisor). Each JSON records how many other probe
# processes ran at solve start/end.
set -u
# raw JSONs were lost from /tmp in the 2026-11-27 reboot: results now go
# to a persistent dir (override with BRAIN_RUNS_DIR)
OUT="${BRAIN_RUNS_DIR:-$HOME/brain-runs}"; mkdir -p "$OUT"
cd "$(dirname "$0")/.."
python -m pip install --quiet "numpy==2.2.6" "scipy==1.15.3" "pydantic==2.11.7" "ortools==9.12.4544" "highspy==1.9.0" 2>&1 | grep -v -i "notice\|warning\|consider" 
run_one() {
  cls=$1; n=$2; f="cs-$cls-$n.json"
  [ -f "$OUT/done-$f" ] && { echo "skip $f"; return; }
  MS_N=$n MS_CLASS=$cls MS_LIMIT=600 MS_CAP_SOLVE_S=2 MS_SOLVERS="highspy:1" MS_OUT=$OUT/$f PYTHONPATH=packages/brain-core \
    timeout 10800 python benchmarks/monolith_scaling.py > $OUT/cs-$cls-$n.log 2>&1
  rc=$?
  python - "$OUT/$f" "$rc" "$(tail -c 600 $OUT/cs-$cls-$n.log | tr '\n' ' ')" <<'PY'
import json, sys, os
p, rc, tail = sys.argv[1], int(sys.argv[2]), sys.argv[3]
d = json.load(open(p)) if os.path.exists(p) else {"measured": True, "stages": {}}
d["process_exit_code"] = rc
d["outcome"] = ("completed" if rc == 0 else
                "KILLED (exit 137 = SIGKILL, typically out-of-memory)" if rc == 137 else
                "TIMEOUT (10800 s wrapper)" if rc == 124 else f"FAILED exit {rc}")
if rc != 0:
    d["log_tail"] = tail
d["where"] = "GitHub Codespace (4 cores, 16 GB), outside the Actions queue"
json.dump(d, open(p, "w"), indent=1)
PY
  touch "$OUT/done-$f"
}
# phase 1: three in parallel
run_one hard 128 & run_one hard 256 & run_one easy 256 &
wait
# phase 2: alone
for spec in "hard 512" "easy 512" "hard 1024" "easy 1024" "easy 128"; do
  set -- $spec; run_one $1 $2
done
echo ALL-DONE > $OUT/ALL-DONE
