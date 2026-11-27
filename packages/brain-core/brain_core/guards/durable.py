"""Durable result files (guard 5): a measured number survives a crash
or a reboot.

Measured on 2026-11-27 (docs/RUNS.md): raw result JSONs written to
/tmp were lost in a codespace reboot and rows had to be rebuilt "from
report". Two causes, both fixed here:
 1. /tmp is not durable storage. write_run_json mirrors every file
    written under /tmp to BRAIN_RUNS_DIR (default ~/brain-runs), which
    lives on the persistent disk of a codespace or a VM.
 2. Path.write_text is not atomic: a kill mid-write leaves a truncated
    JSON that a resumed runner then trusts or crashes on. Writes go to
    a temp file in the same directory, are fsync'd, then os.replace'd.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def atomic_write_text(path, text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return p


def runs_dir() -> Path:
    return Path(os.environ.get("BRAIN_RUNS_DIR",
                               str(Path.home() / "brain-runs")))


def write_run_json(path, obj, indent: int = 1) -> list[Path]:
    """Atomic write; files under /tmp are mirrored to runs_dir().
    Returns every path written."""
    text = json.dumps(obj, indent=indent, default=str)
    p = Path(path)
    out = [atomic_write_text(p, text)]
    if str(p.resolve()).startswith("/tmp/") \
            and os.environ.get("BRAIN_RUNS_MIRROR", "1") != "0":
        out.append(atomic_write_text(runs_dir() / p.name, text))
    return out
