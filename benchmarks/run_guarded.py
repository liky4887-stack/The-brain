"""Run a result-producing command under the guards, then push.

python benchmarks/run_guarded.py --name N --timeout S --out FILE
    [--stall-s S] [--push-remote URL --push-branch B --push-dir D
     --push-workdir W] -- cmd args...

- the command runs as a child with a hard wall timeout and, when
  --stall-s is set, a LIVENESS stall limit (no growth of its log);
- on exit the --out JSON (if any) passes check_record; findings are
  written next to the result as FILE.guard.json and printed;
- the result, its .guard.json and the log are pushed immediately,
  also when the run failed or was stopped, so a failure is never
  lost with the machine.
Exit code: 0 ok, 2 timeout/stall, 3 command failed, 4 guard findings,
5 push failed (also: push preflight failed, command not started). Progress (flat bound) is a separate monitor
(guards.progress); this runner only sees liveness.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "packages", "brain-core"))
sys.path.insert(0, HERE)


def run(argv, timeout_s, log, stall_s=None, poll=0.5):
    t0 = time.monotonic()
    with open(log, "wb") as lf:
        p = subprocess.Popen(argv, stdout=lf, stderr=subprocess.STDOUT)
        last_size, last_change = -1, time.monotonic()
        while p.poll() is None:
            time.sleep(poll)
            now = time.monotonic()
            size = os.path.getsize(log)
            if size != last_size:
                last_size, last_change = size, now
            if now - t0 > timeout_s:
                p.kill()
                p.wait()
                return "timeout", now - t0
            if stall_s and now - last_change > stall_s:
                p.kill()
                p.wait()
                return "stalled (no output)", now - t0
    return ("ok" if p.returncode == 0 else f"exit {p.returncode}"), \
        time.monotonic() - t0


def main(a):
    from brain_core.guards.anomaly import check_record
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".",
                exist_ok=True)
    log = a.out + ".log"
    if a.push_remote and not a.no_preflight:
        # stop loudly BEFORE the run if the result cannot be pushed
        from push_result import PushFailed, preflight_push
        try:
            print("PREFLIGHT:", preflight_push(
                a.push_remote, a.push_branch, a.push_workdir), flush=True)
        except (PushFailed, OSError, subprocess.SubprocessError) as e:
            print("PREFLIGHT FAILED, command NOT started:", e,
                  flush=True)
            return 5
    status, wall = run(a.cmd, a.timeout, log, a.stall_s)
    report = {"name": a.name, "status": status, "wall_s": round(wall, 2),
              "findings": []}
    code = 0
    if status != "ok":
        code = 2 if status.startswith(("timeout", "stalled")) else 3
    elif os.path.isfile(a.out):
        try:
            rec = json.load(open(a.out))
            for k, v in (rec.get("solves") or {"": rec}).items():
                for f in check_record(v if isinstance(v, dict) else {}):
                    if f.rule != "nan_or_missing":
                        report["findings"].append(
                            [k, f.rule, f.detail])
        except Exception as e:
            report["findings"].append(["", "unreadable_result", str(e)])
        if report["findings"]:
            code = 4
    else:
        report["findings"].append(["", "missing_result", a.out])
        code = 4
    gj = a.out + ".guard.json"
    json.dump(report, open(gj, "w"), indent=1)
    print("GUARD:", json.dumps(report), flush=True)
    if a.push_remote:
        from push_result import PushFailed, push_files
        files = [x for x in (a.out, gj, log) if os.path.isfile(x)]
        try:
            print("PUSH:", push_files(files, a.push_remote,
                                      a.push_branch, a.push_dir,
                                      a.push_workdir,
                                      message=f"result {a.name}"),
                  flush=True)
        except PushFailed as e:
            print("PUSH FAILED:", e, flush=True)
            return 5
    return code


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--timeout", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stall-s", type=float, default=None)
    ap.add_argument("--push-remote")
    ap.add_argument("--push-branch", default="monolith-results")
    ap.add_argument("--push-dir", default="codespace-results")
    ap.add_argument("--push-workdir", default="/workspaces/mr")
    ap.add_argument("--no-preflight", action="store_true")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    a.cmd = [c for c in a.cmd if c != "--"] if a.cmd[:1] == ["--"] \
        else a.cmd
    sys.exit(main(a))
