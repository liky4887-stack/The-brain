"""Run manifest + self-check (guard 1).

A manifest DECLARES the parameters of a run. check_manifest compares
them with the ACTUAL values observed now and returns every mismatch
by name. assert_manifest raises on any mismatch, so a run stops at
the first drift instead of producing a number in the wrong class.
stamp() tags a result row with the manifest hash so it cannot be
filed under another class. Catches only the keys declared; an
undeclared parameter is not checked (see unchecked_keys).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


class ManifestDrift(RuntimeError):
    pass


@dataclass(frozen=True)
class Manifest:
    declared: dict = field(default_factory=dict)

    def hash(self) -> str:
        # _canon: a set's str() order changes between processes (hash
        # randomisation), so default=str gave one manifest two hashes
        blob = json.dumps(_canon(self.declared), sort_keys=True,
                          default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _canon(v):
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in v.items()}
    if isinstance(v, (set, frozenset)):
        return sorted((_canon(x) for x in v), key=repr)
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    return v


def _same(a, b) -> bool:
    # True == 1 and 1 == 1.0 in Python: a bool where a number was
    # declared (or the reverse) must still count as drift
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def check_manifest(m: Manifest, actual: dict) -> list[str]:
    problems = []
    for k, want in sorted(m.declared.items()):
        if k not in actual:
            problems.append(f"{k}: declared {want!r}, actual MISSING")
        elif not _same(actual[k], want):
            problems.append(f"{k}: declared {want!r}, actual "
                            f"{actual[k]!r}")
    return problems


def unchecked_keys(m: Manifest, actual: dict) -> list[str]:
    return sorted(set(actual) - set(m.declared))


def assert_manifest(m: Manifest, actual: dict, where: str = "") -> None:
    p = check_manifest(m, actual)
    if p:
        raise ManifestDrift(f"manifest drift at {where or 'step'}: "
                            + "; ".join(p))


def stamp(row: dict, m: Manifest) -> dict:
    out = dict(row)
    out["manifest_hash"] = m.hash()
    out["manifest"] = dict(m.declared)
    return out


def accept_row(row: dict, m: Manifest) -> list[str]:
    """Reject a row filed against the wrong manifest."""
    if row.get("manifest_hash") != m.hash():
        return [f"row manifest_hash {row.get('manifest_hash')!r} != "
                f"{m.hash()!r}: wrong class/table"]
    return []


def observed_environment() -> dict:
    import platform
    import sys
    out = {"python": platform.python_version()}
    for mod in ("numpy", "scipy", "ortools", "highspy", "pyvrp"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:
            out[mod] = "absent"
    out["platform"] = sys.platform
    return out
