"""Machine-readable completion claim (docs/COMPLETION-VERIFICATION.md).

A close-out claim is data the pipeline checks; the claimant's prose is
never evidence. Unknown/extra fields are rejected so a claim cannot
smuggle unaudited content past the schema.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Recompute:
    cmd: str
    expect: dict[str, float | int | str] = field(default_factory=dict)
    tolerance: float = 1e-6


@dataclass(frozen=True)
class Claim:
    title: str
    sha: str
    remote: str = "origin"
    branch: str = "main"
    tests: dict[str, int] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    recompute: Recompute | None = None
    report_file: str | None = None
    deliverables: list[str] = field(default_factory=list)

    @staticmethod
    def from_json(path: str) -> "Claim":
        raw = json.load(open(path))
        known = {"title", "sha", "remote", "branch", "tests",
                 "artifacts", "recompute", "report_file", "deliverables"}
        extra = set(raw) - known
        if extra:
            raise ValueError(f"claim has unaudited fields: {sorted(extra)}")
        rc = raw.get("recompute")
        return Claim(
            title=raw["title"], sha=raw["sha"],
            remote=raw.get("remote", "origin"),
            branch=raw.get("branch", "main"),
            tests=raw.get("tests", {}),
            artifacts=raw.get("artifacts", []),
            recompute=Recompute(rc["cmd"], rc.get("expect", {}),
                                rc.get("tolerance", 1e-6)) if rc else None,
            report_file=raw.get("report_file"),
            deliverables=raw.get("deliverables", []))
