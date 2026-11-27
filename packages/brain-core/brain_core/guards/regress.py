"""Regression compare vs the last recorded numbers of the SAME class.

compare(new, ref) refuses to compare rows of different class keys
(class_key must be equal) and flags: objective worse than the
reference beyond rel_tol, validator problems, wall time above
wall_factor x reference. It never averages across classes.
"""
from __future__ import annotations

CLASS_KEYS = ("pool", "caps_v", "regime", "n", "seed", "time_limit_s")


def class_of(row: dict) -> tuple:
    return tuple(row.get(k) for k in CLASS_KEYS)


def compare(new: dict, ref: dict, rel_tol: float = 1e-6,
            wall_factor: float = 2.0,
            better_tol: float = 0.05) -> list[str]:
    missing = [k for k in CLASS_KEYS
               if new.get(k) is None or ref.get(k) is None]
    if missing:
        # before: two rows that both LACKED the keys had equal class
        # tuples (None, None, ...) and were compared as one class
        return [f"class key(s) missing: {missing}; not comparable"]
    if class_of(new) != class_of(ref):
        return [f"class differs: {class_of(new)} vs {class_of(ref)}; "
                "not comparable"]
    out = []
    a, b = new.get("objective"), ref.get("objective")
    if a is not None and b is not None \
            and a > b + rel_tol * max(1.0, abs(b)):
        out.append(f"objective worse: {a} vs ref {b}")
    if a is not None and b is not None \
            and a < b - better_tol * max(1.0, abs(b)):
        # same class, same seed, much better objective: a model or
        # data change, not luck. Flag it for review; never celebrate.
        out.append(f"objective suspiciously better: {a} vs ref {b} "
                   f"(> {better_tol:.0%}); check model/data drift")
    if new.get("validation_problems"):
        out.append("validation problems present")
    nw, rw = new.get("wall_s"), ref.get("wall_s")
    if nw is not None and rw and nw > wall_factor * rw:
        out.append(f"wall {nw}s > {wall_factor}x ref {rw}s")
    return out
