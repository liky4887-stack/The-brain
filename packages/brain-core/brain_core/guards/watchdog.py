"""Step watchdog + heartbeat + checkpoint/resume (guard 3).

run_step runs fn in a separate process with a hard timeout and a
heartbeat file. A hung, killed or crashing step is returned as a
named StepResult(status != 'ok') - never a silent stall. Checkpoint
records finished steps so a restart skips them.
Catches: hang (timeout), worker killed, exception, out-of-disk guard.
Does not catch: a step that is slow but within its timeout and wrong.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import time
import traceback
from dataclasses import dataclass


@dataclass
class StepResult:
    name: str
    status: str            # ok | timeout | killed | error | low_disk
    wall_s: float
    value: object = None
    detail: str = ""


def _child(fn, args, q, hb):
    try:
        if hb:
            with open(hb, "w") as f:
                f.write(str(time.time()))
        q.put(("ok", fn(*args)))
    except BaseException:
        q.put(("error", traceback.format_exc()))


def run_step(name, fn, args=(), timeout_s=60.0, heartbeat_path=None,
             min_free_disk_bytes=0, disk_path="/tmp"):
    t0 = time.monotonic()
    if min_free_disk_bytes and shutil.disk_usage(
            disk_path).free < min_free_disk_bytes:
        return StepResult(name, "low_disk", 0.0,
                          detail=f"free < {min_free_disk_bytes}")
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_child, args=(fn, args, q, heartbeat_path))
    p.start()
    # Read the result WHILE waiting. Joining first deadlocks a child
    # whose result exceeds the pipe buffer (~64 KB): it blocks in
    # q.put, the join times out and a healthy step is mislabelled
    # "timeout" and lost (measured 2026-11-27 on 100 KB results).
    import queue as _queue
    kind = payload = None
    deadline = t0 + timeout_s
    while True:
        try:
            kind, payload = q.get(timeout=0.2)
            break
        except _queue.Empty:
            pass
        if not p.is_alive():
            try:
                kind, payload = q.get(timeout=2)
            except _queue.Empty:
                pass
            break
        if time.monotonic() > deadline:
            p.kill()
            p.join()
            return StepResult(name, "timeout", time.monotonic() - t0,
                              detail=f"killed after {timeout_s}s")
    p.join(5)
    if p.is_alive():
        p.kill()
        p.join()
    wall = time.monotonic() - t0
    if kind is None:
        return StepResult(name, "killed", wall,
                          detail=f"exit code {p.exitcode}, no result")
    if kind == "ok":
        return StepResult(name, "ok", wall, value=payload)
    return StepResult(name, "error", wall, detail=payload[-800:])


class Checkpoint:
    def __init__(self, path):
        self.path = path
        self.done = {}
        if os.path.exists(path):
            with open(path) as f:
                self.done = json.load(f)

    def has(self, name):
        return name in self.done

    def mark(self, name, value):
        self.done[name] = value
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.done, f)
        os.replace(tmp, self.path)

    def run(self, name, fn, args=(), **kw):
        if self.has(name):
            return StepResult(name, "ok", 0.0, self.done[name],
                              "resumed from checkpoint")
        r = run_step(name, fn, args, **kw)
        if r.status == "ok":
            self.mark(name, r.value)
        return r
