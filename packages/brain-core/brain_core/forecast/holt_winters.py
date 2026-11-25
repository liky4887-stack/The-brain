"""Forecasts with ranges feeding safety stock (Stage 3, slice 3).

Additive Holt-Winters (level + trend + seasonality) over weekly
demand, with a residual-based forecast range, a rolling-origin
back-test against the seasonal-naive baseline (the Stage 3 gate:
beat it), and conversion of forecast sigma into safety stock on the
canonical buffers.

Honesty rules honored:
- The forecaster is a small model ZOO (Holt-Winters over a smoothing
  grid, seasonal-naive, seasonal-naive-with-drift). Which model is
  used is decided per SKU, at each decision time, by measured
  rolling-origin MAE over the history's own recent folds - the model
  family is never assumed to win, and the naive baselines stay in
  the zoo so the selector can fall back to them when they are
  genuinely better.
- "Beats seasonal-naive" is decided by measured rolling-origin MAE
  on the same history, never asserted from the model family. The
  gate: never meaningfully worse per SKU, materially better overall.
- Forecast ranges come from in-sample one-step residuals; coverage is
  measured in the back-test and reported, not assumed to be 95%.
- numpy + stdlib only (decision 4: no new dependency).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np

Z_95 = 1.645  # one-sided 95% service level


@dataclass(frozen=True)
class Forecast:
    mean: float
    sigma: float             # one-step residual std
    lower: float             # mean - Z_95 * sigma, floored at 0
    upper: float             # mean + Z_95 * sigma
    alpha: float
    beta: float
    gamma: float

    @property
    def safety_stock(self) -> float:
        """Units covering one period of demand uncertainty at 95%."""
        return Z_95 * self.sigma


def seasonal_naive_forecast(history: list[float], season: int) -> float:
    """The baseline: next period = same period last season."""
    if len(history) < season:
        return float(np.mean(history)) if history else 0.0
    return history[-season]


def _hw_fit(history: np.ndarray, season: int,
            alpha: float, beta: float, gamma: float,
            multiplicative: bool = False
            ) -> tuple[np.ndarray, float, float, np.ndarray]:
    """Run the recursions; return (fitted one-step means, level,
    trend, seasonal vector). Multiplicative: seasonal indices are
    ratios around 1.0 (tracks growing amplitude); additive: absolute
    offsets."""
    n = len(history)
    if n < 2 * season:
        raise ValueError(f"need >= {2 * season} points for season "
                         f"{season}, got {n}")
    # Classical-decomposition init: trend from the year means, and
    # seasonal indices averaged over ALL available seasons. Initializing
    # from only the first season leaves the seasonal vector dominated
    # by that season's noise for many cycles (gamma is small), which
    # measurably loses to seasonal-naive on high-amplitude series.
    n_seas = n // season
    year_means = [history[i * season:(i + 1) * season].mean()
                  for i in range(n_seas)]
    level = year_means[0]
    trend = (year_means[-1] - year_means[0]) \
        / max(season * (n_seas - 1), 1)
    lvl_t = np.array([level + trend * t for t in range(n)])
    if multiplicative:
        ratios = history / np.maximum(lvl_t, 1e-9)
        seas = np.array([np.mean([ratios[t]
                                  for t in range(w, n, season)])
                         for w in range(season)])
        seas *= season / seas.sum()  # normalize mean index to 1
    else:
        res = history - lvl_t
        seas = np.array([np.mean([res[t]
                                  for t in range(w, n, season)])
                         for w in range(season)])
    fitted = np.zeros(n)
    fitted[:season] = history[:season]
    for t in range(season, n):
        s_idx = t % season
        if multiplicative:
            fitted[t] = (level + trend) * seas[s_idx]
            prev_level = level
            level = alpha * (history[t] / max(seas[s_idx], 1e-9)) \
                + (1 - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (1 - beta) * trend
            seas[s_idx] = gamma * (history[t] / max(level, 1e-9)) \
                + (1 - gamma) * seas[s_idx]
        else:
            fitted[t] = level + trend + seas[s_idx]
            prev_level = level
            level = alpha * (history[t] - seas[s_idx]) \
                + (1 - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (1 - beta) * trend
            seas[s_idx] = gamma * (history[t] - level) \
                + (1 - gamma) * seas[s_idx]
    return fitted, level, trend, seas


"""A candidate is ("hw", alpha, beta, gamma, multiplicative), "sn"
(seasonal-naive) or "sn_drift" (seasonal-naive + mean year-over-year
drift). The naive baselines are candidates, not just yardsticks: the
selector can fall back to them when Holt-Winters genuinely loses."""
_GRID = [("hw", a, b, g, m)
         for m in (True, False)
         for a in (0.1, 0.2, 0.4)
         for b in (0.02, 0.1)
         for g in (0.1, 0.3)]
_ZOO = _GRID + ["sn", "sn_drift"]


def _predict(history: np.ndarray, season: int, candidate) -> float:
    """One-step-ahead prediction of the next point."""
    n = len(history)
    if candidate == "sn":
        return float(history[n - season])
    if candidate == "sn_drift":
        drift = float(np.mean([(history[j] - history[j - season])
                               / season
                               for j in range(n - season, n)]))
        return float(history[n - season] + drift)
    _, a, b, g, mult = candidate
    _, level, trend, seas = _hw_fit(history, season, a, b, g,
                                    multiplicative=mult)
    if mult:
        return float((level + trend) * seas[n % season])
    return float(level + trend + seas[n % season])


def _fitted_one_step(history: np.ndarray, season: int,
                     candidate) -> np.ndarray:
    """One-step fitted means over the history (for residuals/sigma).

    Entries before 2*season are NaN: not enough state yet.
    """
    n = len(history)
    fitted = np.full(n, np.nan)
    if candidate == "sn":
        fitted[season:] = history[:-season]
    elif candidate == "sn_drift":
        for t in range(2 * season, n):
            drift = float(np.mean([(history[j] - history[j - season])
                                   / season
                                   for j in range(t - season, t)]))
            fitted[t] = history[t - season] + drift
    else:
        _, a, b, g, mult = candidate
        f, *_ = _hw_fit(history, season, a, b, g, multiplicative=mult)
        fitted[:] = f
        fitted[:2 * season] = np.nan
    return fitted


def _select(history: np.ndarray, season: int,
            inner_folds: int = 8) -> object:
    """Pick the zoo candidate with the best measured rolling-origin
    MAE over the history's own most recent folds. This mirrors how the
    model will be used (re-selected at each decision time) and keeps
    the choice evidence-based per SKU instead of assumed."""
    n = len(history)
    folds = max(1, min(inner_folds, n - 2 * season))
    best, best_mae = _ZOO[0], math.inf
    for cand in _ZOO:
        errs = []
        for k in range(folds, 0, -1):
            sub = history[:n - k]
            if len(sub) < 2 * season:
                continue
            errs.append(abs(_predict(sub, season, cand)
                            - history[n - k]))
        if errs:
            mae = float(np.mean(errs))
            if mae < best_mae:
                best, best_mae = cand, mae
    return best


def forecast(history: list[float], season: int,
             tune: bool = True) -> Forecast:
    """One-period-ahead forecast with a residual-based range.

    With tune=True (default) the model is selected from the zoo by
    measured back-test error (_select); with tune=False a fixed
    additive Holt-Winters is used.
    """
    h = np.asarray(history, dtype=float)
    if tune:
        cand = _select(h, season)
    else:
        cand = ("hw", 0.3, 0.05, 0.1, False)
    mean = _predict(h, season, cand)
    resid = (h - _fitted_one_step(h, season, cand))[2 * season:]
    sigma = float(resid.std(ddof=1)) if len(resid) > 1 else 0.0
    if cand in ("sn", "sn_drift"):
        a = b = g = 0.0
    else:
        _, a, b, g, _ = cand
    return Forecast(mean=mean, sigma=sigma,
                    lower=max(0.0, mean - Z_95 * sigma),
                    upper=mean + Z_95 * sigma,
                    alpha=a, beta=b, gamma=g)


def rolling_origin_mae(history: list[float], season: int,
                       origins: int = 8, tune: bool = True
                       ) -> tuple[float, float, float]:
    """(holt_winters MAE, seasonal-naive MAE, range coverage).

    Rolling origin over the last `origins` points. Model selection
    (_select over the zoo) is re-run per fold: that is what a planner
    would do at each decision time, so the back-test measures the real
    decision procedure, selector included.
    """
    h = list(history)
    hw_err, sn_err, covered = [], [], 0
    for k in range(origins, 0, -1):
        train, actual = h[:-k], h[-k]
        if len(train) < 2 * season:
            continue
        f = forecast(train, season, tune=tune)
        hw_err.append(abs(f.mean - actual))
        sn_err.append(abs(seasonal_naive_forecast(train, season)
                          - actual))
        if f.lower <= actual <= f.upper:
            covered += 1
    n = len(hw_err)
    return (float(np.mean(hw_err)), float(np.mean(sn_err)),
            covered / n if n else 0.0)


def make_synthetic_history(sku_count: int, weeks: int, season: int,
                           seed: int = 0, noise: float = 0.1,
                           trend_per_week: float = 0.002
                           ) -> dict[str, list[float]]:
    """Weekly demand with base + trend + seasonal block + noise.

    The seasonal amplitude GROWS with the base (multiplicative-ish
    noise structure): seasonal-naive lags both the trend and the
    amplitude drift, which is exactly what Holt-Winters tracks.
    """
    rng = random.Random(seed)
    out = {}
    for i in range(sku_count):
        base = rng.uniform(500, 2000)
        phase = rng.randrange(season)
        series = []
        for t in range(weeks):
            level = base * (1 + trend_per_week * t)
            seas = 0.3 * level * math.sin(
                2 * math.pi * (t + phase) / season)
            series.append(max(0.0, level + seas
                              + rng.gauss(0, noise * level)))
        out[f"SKU-{i:04d}"] = series
    return out


def apply_safety_stock(factory, stocks: dict[str, float]):
    """Set buffer.minimum = safety stock per SKU (in place + report).

    Only existing buffers are touched; SKUs without a buffer are
    reported, not invented.
    """
    touched, missing = [], []
    for b in factory.buffers:
        if b.item in stocks:
            b.minimum = max(b.minimum, stocks[b.item])
            touched.append(b.item)
    for s in stocks:
        if s not in {b.item for b in factory.buffers}:
            missing.append(s)
    return {"touched": sorted(touched), "missing_buffer": sorted(missing)}
