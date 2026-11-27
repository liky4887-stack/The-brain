"""Per-run data-error report: every problem traces back to a source row.

Builds on IngestReport. Three origins are merged into one list:
- "ingest": findings from load_csvs (already carry table + row; this adds
  the file name and the file line, header = line 1).
- "validator" / "solver": problem strings produced after ingest (the
  independent validator's `problems`, a solver's infeasibility/conflict
  messages). Each string is attributed to source rows by matching the
  NAMES of known records (resources, items/SKUs, demands, operations) as
  whole tokens in the text.

Honesty rules:
- The attribution of validator/solver text is a TEXT MATCH on record
  names, labelled method="name-match"; it is not a structural proof.
  Names of length < 2 or purely numeric are not matched (too ambiguous).
- A problem with no matched record is kept, origin as given, with
  sources=[] and counted in `unattributed`; nothing is dropped.
- Ingest findings with row 0 (whole file) point at the file, line 0.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from .csv_io import TABLES, IngestReport

# table -> columns forming the record's natural key
NATURAL_KEY = {
    "locations": ("name",), "calendars": ("name",), "items": ("name",),
    "resources": ("name",), "operations": ("name",), "demands": ("name",),
    "buffers": ("item", "location"),
    "setuprules": ("matrix", "fromsetup", "tosetup"),
}
# tables whose key (single column) names a thing that problem texts mention
MATCHABLE = ("resources", "items", "demands", "operations", "locations")


@dataclass(frozen=True)
class SourceRef:
    table: str
    file: str
    row: int          # 1-based data row (0 = whole file)
    line: int         # 1-based line in the file (header = 1; 0 = whole file)
    key: str = ""


@dataclass
class SourceIndex:
    refs: dict = field(default_factory=dict)  # (table, key) -> [SourceRef]

    def lookup(self, table: str, key: str) -> list[SourceRef]:
        return self.refs.get((table, key), [])


def index_sources(directory: str | Path) -> SourceIndex:
    """Natural key -> source row for every CSV under `directory`."""
    directory = Path(directory)
    idx = SourceIndex()
    for table, (fname, _req, _opt) in TABLES.items():
        path = directory / fname
        if not path.exists() or table not in NATURAL_KEY:
            continue
        with open(path, newline="") as fh:
            for n, raw in enumerate(csv.DictReader(fh), start=1):
                row = {k: (v or "").strip() for k, v in raw.items() if k}
                key = "|".join(row.get(c, "") for c in NATURAL_KEY[table])
                idx.refs.setdefault((table, key), []).append(
                    SourceRef(table, fname, n, n + 1, key))
    return idx


@dataclass(frozen=True)
class DataError:
    origin: str                 # "ingest" | "validator" | "solver"
    severity: str               # "error" | "warning"
    code: str
    message: str
    sources: tuple              # tuple[SourceRef]
    method: str                 # "ingest-row" | "name-match" | "none"


@dataclass
class DataErrorReport:
    entries: list[DataError]
    unattributed: int = 0
    counts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "counts": self.counts, "unattributed": self.unattributed,
            "entries": [{
                "origin": e.origin, "severity": e.severity, "code": e.code,
                "message": e.message, "method": e.method,
                "sources": [{"table": s.table, "file": s.file, "row": s.row,
                             "line": s.line, "key": s.key} for s in e.sources],
            } for e in self.entries]}

    def render(self) -> str:
        lines = [f"data errors: {len(self.entries)} "
                 f"(unattributed: {self.unattributed}) {self.counts}"]
        for e in self.entries:
            where = "; ".join(f"{s.file}:{s.line} ({s.table} {s.key!r})"
                              if s.line else f"{s.file} (whole file)"
                              for s in e.sources) or "no source row matched"
            lines.append(f"[{e.origin}/{e.severity}/{e.code}] {e.message} "
                         f"<- {where} [{e.method}]")
        return "\n".join(lines)


def _tokens_regex(name: str) -> re.Pattern:
    return re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")


def attribute_text(text: str, idx: SourceIndex) -> list[SourceRef]:
    """Source rows of every record whose name occurs as a whole token."""
    out: list[SourceRef] = []
    for (table, key), refs in idx.refs.items():
        if table not in MATCHABLE or len(key) < 2 or key.isdigit():
            continue
        if _tokens_regex(key).search(text):
            out.extend(refs)
    return out


def build_data_error_report(ingest: IngestReport, directory: str | Path,
                            validator_problems=(), solver_problems=()
                            ) -> DataErrorReport:
    idx = index_sources(directory)
    entries: list[DataError] = []
    for f in ingest.findings:
        fname = TABLES[f.table][0] if f.table in TABLES else f.table
        line = f.row + 1 if f.row else 0
        ref = SourceRef(f.table, fname, f.row, line)
        entries.append(DataError("ingest", f.severity, f.code, f.detail,
                                 (ref,), "ingest-row"))
    for origin, probs in (("validator", validator_problems),
                          ("solver", solver_problems)):
        for p in probs:
            refs = attribute_text(str(p), idx)
            entries.append(DataError(
                origin, "error", "problem", str(p), tuple(refs),
                "name-match" if refs else "none"))
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.origin] = counts.get(e.origin, 0) + 1
    un = sum(1 for e in entries if e.origin != "ingest" and not e.sources)
    return DataErrorReport(entries, un, counts)
