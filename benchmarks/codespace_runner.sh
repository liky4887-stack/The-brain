#!/usr/bin/env bash
# Runs the monolith-only scaling probe inside a GitHub Codespace (outside
# the Actions queue). Resumable: sizes already on branch monolith-results
# are skipped. Every result (including killed/OOM) is pushed to branch
# monolith-results with the machine spec inside the JSON. Free quota only.
set -u
cd "$(dirname "$0")/.."
REPO_DIR=$PWD
LOCK=/tmp/codespace_runner.lock
exec 9>"$LOCK"; flock -n 9 || { echo "already running"; exit 0; }
python -m pip install --quiet "numpy==2.2.6" "scipy==1.15.3" "pydantic==2.11.7" "ortools==9.12.4544" "highspy==1.9.0"
RES=/tmp/res
rm -rf "$RES"
if git ls-remote --exit-code --heads origin monolith-results >/dev/null 2>&1; then
  git clone -q --branch monolith-results "$(git remote get-url origin)" "$RES"
else
  git clone -q "$(git remote get-url origin)" "$RES"
  (cd "$RES" && git checkout -q --orphan monolith-results && git rm -rqf . >/dev/null 2>&1; echo "monolith probe results" > README.txt && git add README.txt && git commit -qm init)
fi
cd "$RES" && git config user.name "monolith-probe" && git config user.email "probe@users.noreply.github.com"
cd "$REPO_DIR"
for spec in "hard 128" "hard 256" "easy 256" "hard 512" "easy 512" "hard 1024" "easy 1024" "easy 128"; do
  set -- $spec; cls=$1; n=$2
  f="cs-$cls-$n.json"
  [ -f "$RES/$f" ] && { echo "skip $f"; continue; }
  out=/tmp/$f; rm -f "$out"
  MS_N=$n MS_CLASS=$cls MS_LIMIT=600 MS_CAP_SOLVE_S=2 MS_SOLVERS="highspy:4" MS_OUT=$out PYTHONPATH=packages/brain-core \
    timeout 10800 python benchmarks/monolith_scaling.py > /tmp/cs-$cls-$n.log 2>&1
  rc=$?
  python - "$out" "$rc" "$(tail -c 600 /tmp/cs-$cls-$n.log | tr '\n' ' ')" <<'PY'
import json, sys, os
p, rc, tail = sys.argv[1], int(sys.argv[2]), sys.argv[3]
d = json.load(open(p)) if os.path.exists(p) else {"measured": True, "stages": {}}
d["process_exit_code"] = rc
d["outcome"] = ("completed" if rc == 0 else
                "KILLED (exit 137 = SIGKILL, typically out-of-memory)" if rc == 137 else
                "TIMEOUT (10800 s wrapper)" if rc == 124 else f"FAILED exit {rc}")
if rc != 0:
    d["log_tail"] = tail
d["where"] = "GitHub Codespace, outside the Actions queue"
json.dump(d, open(p, "w"), indent=1)
PY
  cp "$out" "$RES/$f"
  (cd "$RES" && git add "$f" && git commit -qm "result $f (exit $rc)" && git push -q origin HEAD:refs/heads/monolith-results) || echo "push failed for $f"
done
echo ALL-DONE
