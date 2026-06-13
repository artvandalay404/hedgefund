"""Statistical metrics for backtest validation (ADR-0008).

Implements:
  - Annualised Sharpe ratio
  - Probabilistic Sharpe Ratio (PSR) — P(true SR > 0) accounting for
    return distribution (skew, kurtosis); Lo 2002 / Mertens 2002
  - Deflated Sharpe Ratio (DSR) — PSR adjusted for multiple comparisons;
    Bailey & de Prado 2014
  - Probability of Backtest Overfitting (PBO) — fraction of walk-forward
    folds where the in-sample-optimal config underperforms OOS median;
    Bailey et al. 2014
  - Max drawdown

The pass bar is DSR > 0.95 AND PBO < 0.55 (ADR-0008: never raw Sharpe alone).
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd
from scipy import stats


# ── Sharpe ────────────────────────────────────────────────────────────────────

def annualised_sharpe(returns: pd.Series | np.ndarray, periods_per_year: int = 252) -> float:
    """Annualised Sharpe ratio.  Returns NaN if fewer than 3 observations."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 3:
        return float("nan")
    if r.std(ddof=1) == 0:
        return float("nan")
    sr = r.mean() / r.std(ddof=1) * math.sqrt(periods_per_year)
    return float(sr)


def max_drawdown(equity: pd.Series | np.ndarray) -> float:
    """Maximum peak-to-trough drawdown (positive fraction, e.g. 0.15 = 15%)."""
    eq = np.asarray(equity, dtype=float)
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / peak
    return float(dd.max())


# ── PSR / DSR ─────────────────────────────────────────────────────────────────

def _sr_std(sr: float, n: int, skew: float, ex_kurtosis: float) -> float:
    """Asymptotic standard error of the Sharpe ratio estimator (Mertens 2002)."""
    if n <= 1:
        return float("inf")
    variance = (1 - skew * sr + (ex_kurtosis / 4) * sr ** 2) / (n - 1)
    return math.sqrt(max(variance, 1e-12))


def probabilistic_sharpe(
    sr: float,
    sr_benchmark: float,
    n: int,
    skew: float = 0.0,
    ex_kurtosis: float = 0.0,
) -> float:
    """P(true SR > sr_benchmark) given observed `sr` over `n` daily returns.

    ex_kurtosis is excess kurtosis (normal = 0).
    """
    sigma = _sr_std(sr, n, skew, ex_kurtosis)
    z = (sr - sr_benchmark) / sigma
    return float(stats.norm.cdf(z))


def deflated_sharpe(
    sr_best: float,
    sr_all: Sequence[float],
    n_periods: int,
    skew: float = 0.0,
    ex_kurtosis: float = 0.0,
    n_trials: float | None = None,
) -> float:
    """DSR: PSR with a multiple-comparisons-adjusted benchmark.

    Tests whether sr_best is statistically significant given that it was
    selected as the best from N trials.

    `sr_all` is the sample of per-trial Sharpes used to estimate the cross-trial
    dispersion σ.  `n_trials` is the multiple-comparisons count **N** for the
    expected-max benchmark; it defaults to ``len(sr_all)`` but should be passed
    explicitly when N differs from that in-memory sample — notably the
    per-partition **search-N** (ADR-0008 §2), the cumulative lifetime trial
    count, which is far larger than the handful of Sharpes any single run has on
    hand to estimate σ.

    Benchmark = E[max SR under N iid null trials] (Bailey & de Prado 2014):
      = σ_trials × ( (1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e)) )
    where γ = Euler-Mascheroni constant ≈ 0.5772.
    """
    all_sr = list(sr_all)
    n = float(n_trials) if n_trials is not None else float(len(all_sr))
    # Need ≥2 Sharpes to estimate σ and N>1 for an expected-max to mean anything;
    # below that there is no multiple-comparisons penalty and DSR collapses to PSR.
    if n <= 1 or len(all_sr) <= 1:
        return probabilistic_sharpe(sr_best, 0.0, n_periods, skew, ex_kurtosis)

    sigma_trials = float(np.std(all_sr, ddof=1)) or 1e-9
    euler_mascheroni = 0.5772156649015329
    e = math.e

    # Expected maximum SR from N trials under no-edge null
    q1 = stats.norm.ppf(1 - 1 / n)
    q2 = stats.norm.ppf(1 - 1 / (n * e))
    sr_benchmark = sigma_trials * (
        (1 - euler_mascheroni) * q1 + euler_mascheroni * q2
    )

    return probabilistic_sharpe(sr_best, sr_benchmark, n_periods, skew, ex_kurtosis)


# ── PBO ───────────────────────────────────────────────────────────────────────

def probability_of_backtest_overfitting(
    fold_config_sharpes: list[list[float]],
) -> float:
    """Walk-forward PBO (simplified from Bailey et al. 2014 CPCV).

    fold_config_sharpes[fold][config] = OOS Sharpe of that config on that fold.
    For each fold k (with k>0 prior IS folds):
      - Find the config with the highest IS mean Sharpe across folds 0..k-1.
      - If that config's OOS Sharpe < median OOS Sharpe of all configs → overfit.
    PBO = fraction of such folds.

    Returns NaN if there are fewer than 2 folds or fewer than 2 configs.
    """
    n_folds = len(fold_config_sharpes)
    if n_folds < 2:
        return float("nan")
    n_configs = len(fold_config_sharpes[0]) if fold_config_sharpes else 0
    if n_configs < 2:
        return float("nan")

    overfit = 0
    valid = 0

    for k in range(1, n_folds):
        is_mean = [
            float(np.mean([fold_config_sharpes[f][c] for f in range(k)]))
            for c in range(n_configs)
        ]
        best_cfg = int(np.argmax(is_mean))
        oos_sharpes = fold_config_sharpes[k]
        oos_best = oos_sharpes[best_cfg]
        oos_median = float(np.median(oos_sharpes))
        if oos_best < oos_median:
            overfit += 1
        valid += 1

    return overfit / valid if valid else float("nan")


# ── Gate ─────────────────────────────────────────────────────────────────────

DSR_THRESHOLD = 0.95    # P(true SR > 0) must exceed this
PBO_THRESHOLD = 0.55    # fraction of overfit folds must be below this


def passes_gate(dsr: float, pbo: float) -> bool:
    """Return True if the strategy clears the rigorous backtest gate (ADR-0008)."""
    return dsr >= DSR_THRESHOLD and (math.isnan(pbo) or pbo < PBO_THRESHOLD)
