#!/usr/bin/env python
"""Phase 2 walk-forward backtest runner.

Downloads S&P 100 historical bars (cached), runs walk-forward CV over a
parameter grid for the volume-confirmed breakout strategy, logs every trial
to the database, and prints a summary with DSR and PBO gate results.

Usage:
  python scripts/run_backtest.py
  python scripts/run_backtest.py --start 2015-01-01 --end 2022-12-31
  python scripts/run_backtest.py --no-cache
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date

from hedgefund.backtest.data import load_sp100_bars
from hedgefund.backtest.metrics import passes_gate
from hedgefund.backtest.trial_log import TrialLogger
from hedgefund.backtest.validation import WalkForwardCV
from hedgefund.config import configure_logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ── Default date range: IS partition (holdout kept sealed) ───────────────────
DEFAULT_START = date(2015, 1, 1)
DEFAULT_END = date(2022, 12, 31)
IS_PARTITION_NAME = f"sp100_breakout_is_{DEFAULT_START}_{DEFAULT_END}"

# ── Parameter grid ────────────────────────────────────────────────────────────
# Canonical params are the default row; grid tests small variations.
PARAM_GRID = [
    # canonical
    {"breakout_lookback": 20, "volume_lookback": 50, "volume_multiplier": 1.5,
     "stop_pct": 0.02, "reward_risk": 2.0},
    # tighter breakout window
    {"breakout_lookback": 10, "volume_lookback": 50, "volume_multiplier": 1.5,
     "stop_pct": 0.02, "reward_risk": 2.0},
    # longer breakout window
    {"breakout_lookback": 30, "volume_lookback": 50, "volume_multiplier": 1.5,
     "stop_pct": 0.02, "reward_risk": 2.0},
    # higher volume bar
    {"breakout_lookback": 20, "volume_lookback": 50, "volume_multiplier": 2.0,
     "stop_pct": 0.02, "reward_risk": 2.0},
    # tighter stop
    {"breakout_lookback": 20, "volume_lookback": 50, "volume_multiplier": 1.5,
     "stop_pct": 0.015, "reward_risk": 2.0},
    # wider stop, larger reward
    {"breakout_lookback": 20, "volume_lookback": 50, "volume_multiplier": 1.5,
     "stop_pct": 0.03, "reward_risk": 3.0},
]


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Run Phase 2 walk-forward backtest")
    parser.add_argument("--start", default=str(DEFAULT_START))
    parser.add_argument("--end", default=str(DEFAULT_END))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--partition", default=IS_PARTITION_NAME,
        help="Name of the IS partition (used for search-N tracking)"
    )
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    partition = args.partition
    use_cache = not args.no_cache

    log.info("=== Phase 2 Walk-Forward Backtest ===")
    log.info("IS window: %s → %s", start, end)
    log.info("Configurations in grid: %d", len(PARAM_GRID))

    # Load data
    log.info("Loading S&P 100 bars (this may take a moment on first run)...")
    bars = load_sp100_bars(start, end, use_cache=use_cache)
    log.info("Loaded %d rows for %d symbols", len(bars), bars["symbol"].nunique())

    if bars.empty:
        log.error("No bars loaded — check data fetch or cache.")
        return

    # Walk-forward CV
    cv = WalkForwardCV(test_months=6, min_train_months=24, embargo_days=10)
    log.info("Running walk-forward CV...")
    wf_result = cv.run(bars, PARAM_GRID)

    if not wf_result.folds:
        log.error("No folds completed — need more data.")
        return

    n_folds = len(set(f.fold_name for f in wf_result.folds))
    log.info("Completed %d folds × %d configs = %d trials", n_folds, len(PARAM_GRID), len(wf_result.folds))

    # Log trials to DB
    with TrialLogger() as logger:
        for fold in wf_result.folds:
            search_n = logger.increment_search_n(partition)
            logger.log_trial(
                strategy_name="BreakoutStrategy",
                params=fold.params,
                partition_name=partition,
                search_n=search_n,
                annualised_sharpe=fold.oos_sharpe,
                annualised_return=fold.oos_return,
                max_drawdown=fold.oos_max_dd,
                n_trades=fold.oos_n_trades,
                returns=[],   # fold-level returns not stored at this granularity
            )
        current_search_n = logger.get_search_n(partition)

    # Summary
    summary = wf_result.summary()
    print("\n" + "=" * 60)
    print("WALK-FORWARD SUMMARY")
    print("=" * 60)
    print(f"Best params:         {json.dumps(summary['best_params'])}")
    print(f"OOS mean Sharpe:     {summary['oos_mean_sharpe']:.3f}")
    print(f"PSR:                 {summary['psr']:.3f}  (P(true SR > 0))")
    print(f"DSR:                 {summary['dsr']:.3f}  (deflated for {summary['n_trials']} trials)")
    print(f"PBO:                 {summary['pbo']:.3f}  (fraction overfit folds)")
    print(f"search_n (partition):{current_search_n}")
    print(f"Gate:                {'PASS ✓' if summary['passes_gate'] else 'FAIL ✗'}")
    print("=" * 60)

    if summary["passes_gate"]:
        print("\nStrategy passes the rigorous backtest gate.")
        print("Next step: run scripts/evaluate_holdout.py with --confirm-holdout-touch")
    else:
        print(
            "\nStrategy does NOT pass the gate.  "
            "Do not touch the holdout — refine within IS data."
        )
        print(f"  DSR must be ≥ 0.95 (currently {summary['dsr']:.3f})")
        print(f"  PBO must be < 0.55 (currently {summary['pbo']:.3f})")

    print(f"\nAll {len(wf_result.folds)} trial results logged to DB (search_n now {current_search_n}).")


if __name__ == "__main__":
    main()
