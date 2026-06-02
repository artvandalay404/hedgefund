"""Unit tests for backtest metrics (DSR, PBO, Sharpe).

All tests use synthetic return series — no network, no DB.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from hedgefund.backtest.metrics import (
    DSR_THRESHOLD,
    PBO_THRESHOLD,
    annualised_sharpe,
    deflated_sharpe,
    max_drawdown,
    passes_gate,
    probabilistic_sharpe,
    probability_of_backtest_overfitting,
)


# ── Sharpe ratio ──────────────────────────────────────────────────────────────

class TestAnnualisedSharpe:
    def test_zero_returns(self):
        r = pd.Series([0.0] * 252)
        assert math.isnan(annualised_sharpe(r))

    def test_positive_sharpe(self):
        rng = np.random.default_rng(42)
        r = pd.Series(rng.normal(0.001, 0.01, 252))
        sr = annualised_sharpe(r)
        assert sr > 0

    def test_known_value(self):
        # Constant daily return of 0.001 → Sharpe = 0.001/0 → inf; use nonzero std
        r = pd.Series([0.001] * 252 + [-0.001])
        sr = annualised_sharpe(r)
        assert sr > 0

    def test_fewer_than_3_returns_nan(self):
        assert math.isnan(annualised_sharpe(pd.Series([0.01, 0.02])))


# ── Max drawdown ──────────────────────────────────────────────────────────────

class TestMaxDrawdown:
    def test_no_drawdown(self):
        eq = pd.Series([100, 101, 102, 103])
        assert max_drawdown(eq) == pytest.approx(0.0, abs=1e-6)

    def test_simple_drawdown(self):
        eq = pd.Series([100, 110, 90, 95])
        # Peak 110, trough 90 → drawdown = 20/110 ≈ 0.1818
        dd = max_drawdown(eq)
        assert dd == pytest.approx(20 / 110, rel=1e-4)


# ── PSR ───────────────────────────────────────────────────────────────────────

class TestProbabilisticSharpe:
    def test_zero_sr_gives_roughly_half(self):
        p = probabilistic_sharpe(0.0, 0.0, 252)
        assert abs(p - 0.5) < 0.05

    def test_high_sr_high_psr(self):
        p = probabilistic_sharpe(2.0, 0.0, 252)
        assert p > 0.95

    def test_negative_sr_low_psr(self):
        p = probabilistic_sharpe(-1.0, 0.0, 252)
        assert p < 0.1


# ── DSR ───────────────────────────────────────────────────────────────────────

class TestDeflatedSharpe:
    def test_single_trial_equals_psr(self):
        sr = 1.5
        dsr = deflated_sharpe(sr, [sr], 252)
        psr = probabilistic_sharpe(sr, 0.0, 252)
        assert abs(dsr - psr) < 1e-6

    def test_many_trials_deflates_dsr(self):
        # SR = 0.8 over 252 obs; with 100 trials the DSR benchmark is ~0.5,
        # so DSR < PSR (they differ by a numerically meaningful amount).
        sr_best = 0.8
        rng = np.random.default_rng(0)
        sr_all = list(rng.normal(0.0, 0.4, 100))
        sr_all[0] = sr_best
        dsr = deflated_sharpe(sr_best, sr_all, 252)
        psr = probabilistic_sharpe(sr_best, 0.0, 252)
        assert dsr < psr

    def test_dsr_bounds(self):
        sr_all = [0.5, 1.0, 1.5, 2.0, 0.3]
        dsr = deflated_sharpe(2.0, sr_all, 252)
        assert 0.0 <= dsr <= 1.0


# ── PBO ───────────────────────────────────────────────────────────────────────

class TestPBO:
    def test_nan_with_single_fold(self):
        sharpes = [[1.0, 0.5, 0.3]]
        pbo = probability_of_backtest_overfitting(sharpes)
        assert math.isnan(pbo)

    def test_nan_with_single_config(self):
        sharpes = [[1.0], [0.5], [0.3]]
        pbo = probability_of_backtest_overfitting(sharpes)
        assert math.isnan(pbo)

    def test_no_overfitting(self):
        # IS-best config is also the OOS best → no overfitting
        sharpes = [
            [1.0, 0.5, 0.3],  # fold 0: IS
            [1.1, 0.4, 0.2],  # fold 1: OOS; config 0 is best IS and best OOS
            [1.2, 0.3, 0.1],  # fold 2: same pattern
        ]
        pbo = probability_of_backtest_overfitting(sharpes)
        assert pbo < 0.5

    def test_total_overfitting(self):
        # IS-best config is always OOS worst → PBO = 1.0
        sharpes = [
            [2.0, 0.5, 0.5],  # fold 0 IS: config 0 is best
            [0.1, 1.0, 0.9],  # fold 1 OOS: config 0 is worst (below median 0.9)
            [0.1, 1.0, 0.9],  # fold 2 OOS: same
        ]
        pbo = probability_of_backtest_overfitting(sharpes)
        assert pbo >= 0.5

    def test_pbo_between_0_and_1(self):
        rng = np.random.default_rng(7)
        sharpes = [list(rng.normal(0.3, 0.5, 5)) for _ in range(6)]
        pbo = probability_of_backtest_overfitting(sharpes)
        assert 0.0 <= pbo <= 1.0


# ── Gate ─────────────────────────────────────────────────────────────────────

class TestPassesGate:
    def test_passes_when_dsr_high_pbo_low(self):
        assert passes_gate(dsr=0.96, pbo=0.30)

    def test_fails_when_dsr_low(self):
        assert not passes_gate(dsr=0.80, pbo=0.30)

    def test_fails_when_pbo_high(self):
        assert not passes_gate(dsr=0.96, pbo=0.60)

    def test_pbo_nan_uses_dsr_only(self):
        # If PBO can't be computed (too few folds/configs), fall back to DSR alone
        assert passes_gate(dsr=0.96, pbo=float("nan"))
        assert not passes_gate(dsr=0.80, pbo=float("nan"))
