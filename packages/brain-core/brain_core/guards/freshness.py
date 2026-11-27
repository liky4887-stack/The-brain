"""Stale-input / schema-drift guard (for the serving layer and runs).

check_inputs(payload, spec, now, max_age_s) returns problems:
 - missing or extra required fields (schema drift),
 - wrong type for a declared field,
 - 'as_of' older than max_age_s (stale),
 - content hash different from the declared pinned hash.
Catches only declared fields; semantic wrongness inside valid fields
is not detected.
"""
from __future__ import annotations

import hashlib
import json


def content_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def check_inputs(payload: dict, spec: dict, now: float,
                 max_age_s: float, pinned_hash: str | None = None):
    p = []
    for k, typ in spec.items():
        if k not in payload:
            p.append(f"missing field {k}")
        elif not isinstance(payload[k], typ):
            p.append(f"field {k}: expected {typ.__name__}, got "
                     f"{type(payload[k]).__name__}")
    extra = sorted(set(payload) - set(spec) - {"as_of"})
    if extra:
        p.append(f"unexpected fields {extra}")
    as_of = payload.get("as_of")
    if as_of is None:
        p.append("as_of missing")
    elif now - as_of > max_age_s:
        p.append(f"stale: age {now - as_of:.0f}s > {max_age_s}s")
    if pinned_hash is not None:
        body = {k: v for k, v in payload.items() if k != "as_of"}
        if content_hash(body) != pinned_hash:
            p.append("content hash differs from pinned")
    return p
