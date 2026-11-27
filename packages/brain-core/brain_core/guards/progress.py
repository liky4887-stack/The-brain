"""Progress monitor: measures progress, not liveness (guard 3b).

FlatProgress.update(value) returns True when the best value has not
improved by more than rel_tol (relative) over the last `window`
updates. For a bound that should rise (maximise=True) or a gap that
should fall (maximise=False). A step that is alive but flat is
stopped and recorded by name by the caller.
Catches: flat or regressing bound/gap. Does not catch: slow steady
progress below the tolerance, or progress on a wrong objective.
"""
from __future__ import annotations

# Default window (updates) for the CG restricted-master objective, ON in
# column_generation and therefore in every long runner (benchmark,
# ladder, CG). Derived from MEASURED natural flat stretches, not guessed:
# 10 unseeded CG traces at pools 0.9 (SHA 3b5662e, 14 trace files in
# monolith-results/codespace-results/trace/; the 4 traces at pools 1.0 and
# 1.1 converge in 1 iteration and carry no information). Longest stretch
# in which the restricted-master objective did not improve by more than
# rel_tol (same rule as FlatProgress), over all traces:
#   rel_tol 1e-9 (the guard's tolerance): master 33 (seed 200006),
#                                         bound  25
#   rel_tol 1e-6                        : master 72, bound 51
#   rel_tol 1e-4                        : master 77, bound 72
# Runs took 123 to 290 iterations. N = 100 is 3.0x the longest natural
# flat stretch at the guard's own tolerance (33) and above the longest
# at the loosest tolerance measured (77). It stops a run that is flat for
# 100 iterations, i.e. cannot cut a healthy run; it is NOT a proof that
# no healthy run is ever flatter (10 traces, one class). Disable only
# with an explicit progress_window=None (and say so in the result).
DEFAULT_CG_PROGRESS_WINDOW = 100


class FlatProgress:
    def __init__(self, window: int, rel_tol: float = 1e-9,
                 maximise: bool = True, name: str = "progress"):
        self.window, self.rel_tol = window, rel_tol
        self.maximise, self.name = maximise, name
        self.best = None
        self.since_best = 0
        self.n = 0

    def update(self, value: float) -> bool:
        self.n += 1
        if self.best is None:
            self.best, self.since_best = value, 0
            return False
        gain = (value - self.best) if self.maximise \
            else (self.best - value)
        if gain > self.rel_tol * max(1.0, abs(self.best)):
            self.best, self.since_best = value, 0
        else:
            self.since_best += 1
        return self.since_best >= self.window

    def reason(self) -> str:
        return (f"{self.name} flat: no improvement over "
                f"{self.since_best} updates (best {self.best})")
