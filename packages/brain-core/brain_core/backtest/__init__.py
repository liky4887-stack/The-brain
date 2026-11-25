"""Back-test harness: optimizer vs the documented naive baseline."""

from .harness import (BacktestResult, WeekResult, naive_plan,
                      run_backtest)

__all__ = ["BacktestResult", "WeekResult", "naive_plan", "run_backtest"]
