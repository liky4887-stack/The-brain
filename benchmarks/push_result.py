"""Push finished result files to a results branch the moment they exist.

push_files(files, remote, branch, dest_dir, workdir) copies each file
into a clone of the results branch, commits, pushes, and retries on a
rejected push (fetch+rebase). Returns a dict with the pushed commit.
Failure is loud: a missing file or a push that still fails after the
retries raises PushFailed; nothing is swallowed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time


class PushFailed(RuntimeError):
    pass


def _git(cwd, *a, check=True):
    r = subprocess.run(["git", "-c", "user.name=results-bot",
                        "-c", "user.email=results@invalid", *a],
                       cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise PushFailed(f"git {' '.join(a)}: {r.stderr.strip()[-300:]}")
    return r


def push_files(files, remote, branch, dest_dir, workdir, retries=3,
               message="result"):
    for f in files:
        if not os.path.isfile(f):
            raise PushFailed(f"missing result file {f}")
    if not os.path.isdir(os.path.join(workdir, ".git")):
        r = subprocess.run(["git", "clone", "-q", "--branch", branch,
                            remote, workdir], capture_output=True,
                           text=True)
        if r.returncode:
            raise PushFailed("clone: " + r.stderr.strip()[-300:])
    last = ""
    for attempt in range(retries):
        _git(workdir, "fetch", "-q", "origin", branch)
        _git(workdir, "reset", "-q", "--hard", f"origin/{branch}")
        d = os.path.join(workdir, dest_dir)
        os.makedirs(d, exist_ok=True)
        for f in files:
            shutil.copy2(f, os.path.join(d, os.path.basename(f)))
        _git(workdir, "add", "-A", dest_dir)
        if _git(workdir, "diff", "--cached", "--quiet",
                check=False).returncode == 0:
            return {"status": "nochange", "attempt": attempt}
        _git(workdir, "commit", "-q", "-m", message)
        p = _git(workdir, "push", "-q", "origin", f"HEAD:{branch}",
                 check=False)
        if p.returncode == 0:
            sha = _git(workdir, "rev-parse", "--short", "HEAD").stdout
            return {"status": "pushed", "commit": sha.strip(),
                    "attempt": attempt}
        last = p.stderr.strip()[-300:]
        time.sleep(1)
    raise PushFailed(f"push failed after {retries} attempts: {last}")


def preflight_push(remote, branch, workdir):
    """Prove BEFORE a long run that a push can work: clone/fetch the
    results branch and `git push --dry-run` (contacts the remote with
    write intent, so missing credentials fail here: measured on the
    codespace as 'could not read Username'). Raises PushFailed."""
    if not os.path.isdir(os.path.join(workdir, ".git")):
        r = subprocess.run(["git", "clone", "-q", "--branch", branch,
                            remote, workdir], capture_output=True,
                           text=True)
        if r.returncode:
            raise PushFailed("preflight clone: " + r.stderr.strip()[-300:])
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(["git", "push", "--dry-run", "-q", "origin",
                        f"HEAD:{branch}"], cwd=workdir, env=env,
                       capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise PushFailed("preflight push --dry-run: "
                         + r.stderr.strip()[-300:])
    return {"status": "push-possible"}
