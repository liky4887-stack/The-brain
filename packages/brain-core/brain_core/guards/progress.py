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
