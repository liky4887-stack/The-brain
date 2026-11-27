"""Same input twice gives the same plan (no hidden randomness)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_decompose import H0, _solvable_two_cell_factory
from brain_core.rolling.two_level import solve_window


def _sig(plan):
    return sorted((a.line, a.day, a.seq_pos, a.sku, round(a.qty, 6))
                  for a in plan.assignments), \
        plan.bucket.objective


def test_solve_window_is_deterministic():
    f = _solvable_two_cell_factory()
    runs = [solve_window(f, H0, 2, 480.0, bucket_time_s=5, seq_time_s=2)
            for _ in range(2)]
    assert _sig(runs[0]) == _sig(runs[1])
