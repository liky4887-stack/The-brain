#!/usr/bin/env bash
# lumpy class (setup x200 + 25% min lot): where real branch-and-bound
# starts. Sequential; results /tmp/cs-lumpy-<n>.json with outcome.
cd "$(dirname "$0")/.."
for n in 4 8 16 32 64 128; do
  f=cs-lumpy-$n.json
  MS_N=$n MS_CLASS=lumpy MS_LIMIT=600 MS_CAP_SOLVE_S=2 MS_SOLVERS="highspy:1" MS_OUT=/tmp/$f PYTHONPATH=packages/brain-core \
    timeout 10800 python benchmarks/monolith_scaling.py > /tmp/cs-lumpy-$n.log 2>&1
  rc=$?
  python - "/tmp/$f" "$rc" "$(tail -c 600 /tmp/cs-lumpy-$n.log | tr '\n' ' ')" <<'PY'
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
done
echo ALL > /tmp/lumpy-ALL
