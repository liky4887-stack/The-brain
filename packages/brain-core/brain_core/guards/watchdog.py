"""Step watchdog + heartbeat + checkpoint/resume (guard 3).

run_step runs fn in a separate process with a hard timeout and a
heartbeat file. A hung, killed or crashing step is returned as a
named StepResult(status != 'ok') - never a silent stall. Checkpoint
records finished steps so a restart skips them.
Catches: hang (timeout), worker killed, exception, out-of-disk guard.
Does not catch: a step that is slow but within its timeout and wrong.

Result transport: the parent DRAINS the result queue while it waits.
The old order (join(timeout) first, then q.get) deadlocked on any
result bigger than the OS pipe buffer (~64 KB): the child cannot exit
until its queued payload is read, so join() ran out the clock and a
step that had FINISHED in 0.1 s was killed and reported as "timeout"
(measured: 1 MB string payload, timeout_s=8 -> status timeout, 8.0 s).

Heartbeat: when heartbeat_path is set the child rewrites it every
heartbeat_every_s from a daemon thread. It proves the process is
alive, NOT that it is making progress (a solver stuck inside C code
still beats); progress is what timeout_s bounds.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import queue as _queue
import shutil
import threading
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


def _write_beat(hb):
    tmp = hb + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(time.time()))
    os.replace(tmp, hb)


def _beat_loop(hb, every_s, stop):
    while not stop.wait(every_s):
        try:
            _write_beat(hb)
        except OSError:
            pass


def _child(fn, args, q, hb, hb_every_s=5.0, progress_path=None):
    stop = threading.Event()
    if progress_path:
        os.environ[PROGRESS_ENV] = progress_path
    try:
        if hb:
            _write_beat(hb)
            threading.Thread(target=_beat_loop,
                             args=(hb, hb_every_s, stop),
                             daemon=True).start()
        q.put(("ok", fn(*args)))
    except BaseException:
        q.put(("error", traceback.format_exc()))
    finally:
        stop.set()


PROGRESS_ENV = "BRAIN_PROGRESS_PATH"


def report_progress(marker) -> None:
    """Called from inside long work (one CG iteration, one window) to
    say it MOVED. No-op unless the step runs under run_step with
    stall_s. Unlike the heartbeat thread, a solver stuck in C code
    stops calling this, so the parent sees the stall."""
    path = os.environ.get(PROGRESS_ENV)
    if not path:
        return
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(f"{time.time()} {marker}")
        os.replace(tmp, path)
    except OSError:
        pass


def _progress_mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def heartbeat_age_s(heartbeat_path) -> float | None:
    """Seconds since the child last beat; None when it never did."""
    try:
        with open(heartbeat_path) as f:
            return time.time() - float(f.read().strip() or 0.0)
    except (OSError, ValueError):
        return None


def run_step(name, fn, args=(), timeout_s=60.0, heartbeat_path=None,
             min_free_disk_bytes=0, disk_path="/tmp",
             heartbeat_every_s=5.0, poll_s=0.2, stall_s=None,
             progress_path=None):
    """stall_s: kill with status 'stalled' when the step has not called
    report_progress for stall_s seconds (counted from start until the
    first call). Catches the slow step that is still inside timeout_s
    but has stopped moving."""
    t0 = time.monotonic()
    if min_free_disk_bytes and shutil.disk_usage(
            disk_path).free < min_free_disk_bytes:
        return StepResult(name, "low_disk", 0.0,
                          detail=f"free < {min_free_disk_bytes}")
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    if stall_s is not None and progress_path is None:
        import tempfile
        fd, progress_path = tempfile.mkstemp(prefix="brain-progress-")
        os.close(fd)
        os.unlink(progress_path)
    p = ctx.Process(target=_child, args=(fn, args, q, heartbeat_path,
                                         heartbeat_every_s,
                                         progress_path if stall_s
                                         is not None else None))
    p.start()
    deadline = t0 + timeout_s
    got = None
    last_move, last_mt = time.monotonic(), None
    # drain while waiting: the child can only exit once its result has
    # left the pipe, so reading first is what lets a big result return
    while got is None:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        try:
            got = q.get(timeout=min(poll_s, left))
        except _queue.Empty:
            if stall_s is not None:
                mt = _progress_mtime(progress_path)
                if mt != last_mt:
                    last_mt, last_move = mt, time.monotonic()
                elif time.monotonic() - last_move > stall_s:
                    p.kill()
                    p.join()
                    return StepResult(
                        name, "stalled", time.monotonic() - t0,
                        detail=f"no progress for {stall_s}s "
                               f"(timeout {timeout_s}s not reached)")
            if not p.is_alive():
                # died: one last short read for a result that was
                # flushed just before exit, then report it killed
                try:
                    got = q.get(timeout=1.0)
                except _queue.Empty:
                    break
    wall = time.monotonic() - t0
    if got is None:
        if p.is_alive():
            p.kill()
            p.join()
            return StepResult(name, "timeout", wall,
                              detail=f"killed after {timeout_s}s")
        p.join()
        return StepResult(name, "killed", wall,
                          detail=f"exit code {p.exitcode}, no result")
    p.join(5.0)
    if p.is_alive():          # result is in hand; do not leak the child
        p.kill()
        p.join()
    kind, payload = got
    if kind == "ok":
        return StepResult(name, "ok", wall, value=payload)
    return StepResult(name, "error", wall, detail=payload[-800:])


def _kill_pool(pool):
    """Stop a ProcessPoolExecutor NOW, running tasks included.
    shutdown() alone waits for running tasks; Python 3.14 has
    terminate_workers(), older versions need the worker handles."""
    pool.shutdown(wait=False, cancel_futures=True)
    term = getattr(pool, "terminate_workers", None)
    if term is not None:
        term()
        return
    for p in list((getattr(pool, "_processes", None) or {}).values()):
        try:
            p.kill()
        except Exception:
            pass


def run_pool(fn, jobs, max_workers=None, wall_budget_s=None,
             retry_errors=True):
    """fn(job) for every job in spawn worker processes, failure-
    isolated. Returns one StepResult per job, in job order:
      ok       value = fn(job)
      error    fn raised, or its worker died (BrokenProcessPool)
      timeout  not finished inside wall_budget_s (whole call); the
               workers are killed, so the call ALWAYS returns
    A dead worker breaks the whole executor and fails every pending
    job, innocent ones too; with retry_errors each error job gets ONE
    more run in its own watchdog process (status ok / error / killed /
    timeout), so only a job that fails twice is reported as failed. Timeouts are not retried (a hang hangs
    again)."""
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures import TimeoutError as FutTimeout
    t0 = time.monotonic()
    out: list[StepResult | None] = [None] * len(jobs)
    if not jobs:
        return []
    ctx = multiprocessing.get_context("spawn")
    pool = ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx)
    timed_out = False
    try:
        futs = [pool.submit(fn, j) for j in jobs]
        for i, fut in enumerate(futs):
            left = None if wall_budget_s is None else \
                wall_budget_s - (time.monotonic() - t0)
            try:
                if left is not None and left <= 0:
                    raise FutTimeout()
                v = fut.result(timeout=left)
                out[i] = StepResult(f"job {i}", "ok",
                                    time.monotonic() - t0, value=v)
            except FutTimeout:
                timed_out = True
                out[i] = StepResult(
                    f"job {i}", "timeout", time.monotonic() - t0,
                    detail=f"not finished inside the {wall_budget_s}s "
                           "wall budget; worker killed")
            except Exception as exc:
                out[i] = StepResult(
                    f"job {i}", "error", time.monotonic() - t0,
                    detail=f"{type(exc).__name__}: {exc}"[-800:])
    finally:
        if timed_out:
            _kill_pool(pool)
        else:
            pool.shutdown(wait=True)
    if retry_errors:
        again = [i for i, r in enumerate(out) if r.status == "error"]
        if again:
            left = None if wall_budget_s is None else \
                wall_budget_s - (time.monotonic() - t0)
            if left is None or left > 0:
                # each retry in its OWN process: retried together, the
                # job that kills its worker would break the pool again
                # and fail the innocent ones a second time
                second = []
                for i in again:
                    lim = 1e9 if wall_budget_s is None else \
                        wall_budget_s - (time.monotonic() - t0)
                    if lim <= 0:
                        second.append(StepResult(
                            f"job {i}", "timeout", time.monotonic() - t0,
                            detail="no wall budget left for the retry"))
                        continue
                    second.append(run_step(f"job {i}", fn, (jobs[i],),
                                           timeout_s=lim))
                for i, r in zip(again, second):
                    if r.status != "ok":
                        r.detail = (f"failed twice; first: "
                                    f"{out[i].detail[:300]} | second: "
                                    f"{r.detail[:300]}")
                    else:
                        r.detail = ("recovered on retry after: "
                                    + out[i].detail[:300])
                    out[i] = r
    return out


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
