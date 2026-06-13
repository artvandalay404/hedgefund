"""Walk-forward cross-validation and holdout evaluation (ADR-0008).

WalkForwardCV:
  - Expanding-window folds: IS = everything before test window, OOS = test window
  - Embargo of N trading days between IS end and OOS start to prevent leakage
    from overlapping return windows (daily strategy with ~10-day hold time)
  - Returns per-fold IS and OOS metrics for every parameter configuration tested

HoldoutEvaluator:
  - Runs a frozen strategy exactly once against the sealed holdout period
  - Requires explicit human confirmation (--confirm flag or programmatic gate)
  - Every call increments holdout_n for that partition; holdout_n MUST stay ≈ 1
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from typing import Callable

from hedgefund.backtest.engine import Backtester, BacktestResult
from hedgefund.backtest.metrics import (
    annualised_sharpe,
    deflated_sharpe,
    max_drawdown,
    passes_gate,
    probabilistic_sharpe,
    probability_of_backtest_overfitting,
)
from hedgefund.backtest.strategy import BreakoutStrategy, StrategyBase


EMBARGO_DAYS = 10   # trading days removed between IS tail and OOS start


@dataclass
class FoldResult:
    fold_name: str
    is_sharpe: float
    oos_sharpe: float
    oos_return: float
    oos_max_dd: float
    oos_n_trades: int
    params: dict[str, Any]
    oos_returns: list[float] = field(default_factory=list)  # for effective-N (ADR-0010)


@dataclass
class WalkForwardResult:
    folds: list[FoldResult]
    param_grid: list[dict[str, Any]]

    @property
    def oos_sharpes_by_config(self) -> list[list[float]]:
        """fold_config_sharpes[fold_idx][config_idx] for PBO computation."""
        n_folds = len(set(f.fold_name for f in self.folds))
        n_configs = len(self.param_grid)
        grid: list[list[float]] = [[float("nan")] * n_configs for _ in range(n_folds)]
        fold_names = sorted(set(f.fold_name for f in self.folds))
        fold_idx = {name: i for i, name in enumerate(fold_names)}
        config_map = {json.dumps(p, sort_keys=True): i for i, p in enumerate(self.param_grid)}
        for fr in self.folds:
            fi = fold_idx[fr.fold_name]
            ci = config_map.get(json.dumps(fr.params, sort_keys=True), -1)
            if ci >= 0:
                grid[fi][ci] = fr.oos_sharpe
        return grid

    def summary(self, n_trials: float | None = None) -> dict[str, Any]:
        """Aggregate statistics across all folds for the canonical params.

        ``n_trials`` is the multiple-comparisons count N for the DSR deflation.
        It defaults to the number of **distinct configs** evaluated in this run
        (the honest within-run selection count) but should be the per-partition
        **search-N** — the cumulative lifetime trial count the data remembers
        (ADR-0008 §2/§4) — when a caller has it.  Folds are CV slices of a single
        config and never count as trials (ADR-0010 §3).
        """
        # Pick the param config that was best IS on average
        by_config: dict[str, list[FoldResult]] = {}
        for fr in self.folds:
            key = json.dumps(fr.params, sort_keys=True)
            by_config.setdefault(key, []).append(fr)

        best_key = max(by_config, key=lambda k: float(np.mean([f.is_sharpe for f in by_config[k]])))
        best_folds = by_config[best_key]

        oos_sr = [f.oos_sharpe for f in best_folds]
        sr_mean = float(np.mean(oos_sr)) if oos_sr else float("nan")
        sr_returns = [s for s in oos_sr if not np.isnan(s)]

        # Cross-trial dispersion σ is estimated across *configs* (one OOS Sharpe
        # per config), not across fold-results: within-config fold spread is CV
        # noise, not multiple-comparisons dispersion.
        per_config_oos = [
            float(np.mean([f.oos_sharpe for f in folds]))
            for folds in by_config.values()
        ]
        n = n_trials if n_trials is not None else len(by_config)

        psr = probabilistic_sharpe(
            sr_mean, 0.0, max(len(sr_returns) * 63, 1),
            skew=float(np.array(sr_returns).mean() * 0),  # returns-level would need daily, use 0
            ex_kurtosis=0.0,
        )
        dsr = deflated_sharpe(
            sr_mean, per_config_oos,
            n_periods=max(len(sr_returns) * 63, 1),
            n_trials=n,
        )
        pbo = probability_of_backtest_overfitting(self.oos_sharpes_by_config)

        return {
            "best_params": json.loads(best_key),
            "oos_mean_sharpe": sr_mean,
            "oos_sharpes": oos_sr,
            "psr": psr,
            "dsr": dsr,
            "pbo": pbo,
            "passes_gate": passes_gate(dsr, pbo),
            "n_folds": len(best_folds),
            "n_trials": n,
        }


class WalkForwardCV:
    """Expanding-window walk-forward cross-validation.

    Each OOS fold is `test_months` months long.  The IS window includes all
    prior data minus an embargo gap at the tail.
    """

    def __init__(
        self,
        test_months: int = 6,
        min_train_months: int = 24,
        embargo_days: int = EMBARGO_DAYS,
        backtester_kwargs: dict | None = None,
    ):
        self.test_months = test_months
        self.min_train_months = min_train_months
        self.embargo_days = embargo_days
        self.backtester_kwargs = backtester_kwargs or {}

    def run(
        self,
        bars: pd.DataFrame,
        param_grid: list[dict],
        strategy_factory: Callable[[dict], StrategyBase] | None = None,
    ) -> WalkForwardResult:
        """Run walk-forward over all folds and parameter combinations.

        bars: full historical bar DataFrame (IS only — holdout excluded upstream)
        param_grid: list of config-identity dicts (BreakoutStrategy params or
                    DSL config_identity dicts)
        strategy_factory: callable mapping a config dict to a StrategyBase;
                          defaults to BreakoutStrategy(**params)
        """
        if strategy_factory is None:
            strategy_factory = lambda p: BreakoutStrategy(**p)
        bars = bars.copy()
        bars["timestamp"] = pd.to_datetime(bars["timestamp"]).dt.tz_localize(None).dt.normalize()
        trading_days = sorted(bars["timestamp"].unique())

        folds_spec = list(self._fold_specs(trading_days))
        if not folds_spec:
            raise ValueError("Not enough data for walk-forward folds.")

        results: list[FoldResult] = []
        for fold_name, is_end, oos_start, oos_end in folds_spec:
            is_bars = bars[bars["timestamp"] <= is_end]
            oos_bars = bars[
                (bars["timestamp"] >= oos_start) & (bars["timestamp"] <= oos_end)
            ]
            if oos_bars.empty or is_bars.empty:
                continue

            for params in param_grid:
                strat = strategy_factory(params)
                bt = Backtester(strat, **self.backtester_kwargs)

                is_result = bt.run(is_bars)
                oos_result = bt.run(oos_bars)

                results.append(FoldResult(
                    fold_name=fold_name,
                    is_sharpe=annualised_sharpe(is_result.returns),
                    oos_sharpe=annualised_sharpe(oos_result.returns),
                    oos_return=float(
                        oos_result.equity_curve.iloc[-1] / oos_result.start_equity - 1
                    ) if len(oos_result.equity_curve) > 0 else float("nan"),
                    oos_max_dd=max_drawdown(oos_result.equity_curve),
                    oos_n_trades=oos_result.n_trades,
                    params=params,
                    oos_returns=oos_result.returns.tolist(),
                ))

        return WalkForwardResult(folds=results, param_grid=param_grid)

    def _fold_specs(
        self, trading_days: list[pd.Timestamp]
    ) -> list[tuple[str, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
        """Yield (fold_name, is_end, oos_start, oos_end) tuples."""
        if not trading_days:
            return []

        first_day = trading_days[0]
        last_day = trading_days[-1]

        # Minimum IS length in trading days (approx: months × 21)
        min_is_days = self.min_train_months * 21
        test_days = self.test_months * 21

        specs = []
        oos_start_idx = min_is_days + self.embargo_days

        while oos_start_idx < len(trading_days):
            oos_end_idx = min(oos_start_idx + test_days - 1, len(trading_days) - 1)
            is_end_idx = oos_start_idx - self.embargo_days - 1

            if is_end_idx < min_is_days - 1:
                oos_start_idx += test_days
                continue

            is_end = trading_days[is_end_idx]
            oos_start = trading_days[oos_start_idx]
            oos_end = trading_days[oos_end_idx]

            fold_name = f"{oos_start.date()}_{oos_end.date()}"
            specs.append((fold_name, is_end, oos_start, oos_end))
            oos_start_idx = oos_end_idx + 1

        return specs


@dataclass
class HoldoutResult:
    partition_name: str
    holdout_n: int              # should be 1; > 1 means the holdout was reused
    search_n_at_eval: int
    params: dict[str, Any]
    annualised_sharpe: float
    annualised_return: float
    max_drawdown: float
    psr: float
    dsr: float
    n_trades: int
    passes_gate: bool
    returns: list[float] = field(default_factory=list)


class HoldoutEvaluator:
    """One-shot evaluation against the sealed holdout period (ADR-0008).

    Contract: call exactly once per holdout partition.  The caller is
    responsible for incrementing holdout_n in the trial log before calling.
    If holdout_n > 1 the result is flagged as contaminated.
    """

    def __init__(self, backtester_kwargs: dict | None = None):
        self.backtester_kwargs = backtester_kwargs or {}

    def evaluate(
        self,
        bars: pd.DataFrame,
        params: dict,
        holdout_start: date,
        holdout_end: date,
        search_n: int,
        holdout_n: int,
        partition_name: str,
        strategy_factory: Callable[[dict], StrategyBase] | None = None,
    ) -> HoldoutResult:
        if strategy_factory is None:
            strategy_factory = lambda p: BreakoutStrategy(**p)
        holdout_bars = bars[
            (pd.to_datetime(bars["timestamp"]).dt.date >= holdout_start)
            & (pd.to_datetime(bars["timestamp"]).dt.date <= holdout_end)
        ]
        # Provide enough warmup bars for the strategy to generate signals
        warmup_start = bars["timestamp"].min()
        warmup_bars = bars[pd.to_datetime(bars["timestamp"]).dt.date < holdout_start]
        eval_bars = pd.concat([warmup_bars, holdout_bars], ignore_index=True)

        strat = strategy_factory(params)
        bt = Backtester(strat, **self.backtester_kwargs)

        full_result: BacktestResult = bt.run(eval_bars)

        # Measure only the holdout window
        holdout_ts = pd.to_datetime(holdout_start)
        holdout_equity = full_result.equity_curve[
            full_result.equity_curve.index >= holdout_ts
        ]
        if len(holdout_equity) < 2:
            returns = pd.Series(dtype=float)
        else:
            returns = holdout_equity.pct_change().dropna()

        sr = annualised_sharpe(returns)
        ann_ret = float(holdout_equity.iloc[-1] / holdout_equity.iloc[0] - 1) if len(holdout_equity) > 1 else float("nan")
        mdd = max_drawdown(holdout_equity)

        r_arr = returns.tolist()
        skew = float(pd.Series(r_arr).skew()) if len(r_arr) > 2 else 0.0
        exc_kurt = float(pd.Series(r_arr).kurtosis()) if len(r_arr) > 3 else 0.0

        psr = probabilistic_sharpe(sr, 0.0, max(len(r_arr), 2), skew, exc_kurt)
        # The holdout is deflated by holdout_n, NOT search-N: a single frozen
        # strategy touching the holdout once needs no multiple-comparisons
        # deflation — independence is the protection (ADR-0008 §2).  search-N
        # belongs to the in-sample gate (summary()).  n_periods is the return
        # length, where the old call mis-slotted search_n.
        dsr_val = deflated_sharpe(
            sr, [sr], n_periods=max(len(r_arr), 2),
            skew=skew, ex_kurtosis=exc_kurt, n_trials=holdout_n,
        )

        from hedgefund.backtest.metrics import passes_gate as _passes
        gate = _passes(dsr_val, float("nan"))

        # Holdout reuse warning
        if holdout_n > 1:
            import warnings
            warnings.warn(
                f"holdout_n={holdout_n} for partition '{partition_name}': "
                "this holdout has been touched more than once — results are unreliable.",
                stacklevel=2,
            )

        n_holdout_trades = sum(
            1 for t in full_result.trades
            if pd.Timestamp(t.exit_date) >= pd.Timestamp(holdout_start)
        )

        return HoldoutResult(
            partition_name=partition_name,
            holdout_n=holdout_n,
            search_n_at_eval=search_n,
            params=params,
            annualised_sharpe=sr,
            annualised_return=ann_ret,
            max_drawdown=mdd,
            psr=psr,
            dsr=dsr_val,
            n_trades=n_holdout_trades,
            passes_gate=gate,
            returns=r_arr,
        )
