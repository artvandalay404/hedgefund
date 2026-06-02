#!/usr/bin/env python
"""Human-gated one-shot holdout evaluation (ADR-0008).

This script touches the sealed holdout period.  The --confirm-holdout-touch
flag is the explicit human gate that prevents automated loops from reusing it.

CONTRACT:
  - Run this at most ONCE per holdout partition.
  - holdout_n > 1 means the holdout is contaminated; results cannot be trusted.
  - The strategy parameters must be FROZEN before this is called.

Usage (after walk-forward passes the gate):
  python scripts/evaluate_holdout.py --confirm-holdout-touch

Optional overrides:
  --params '{"breakout_lookback":20,"volume_lookback":50,"volume_multiplier":1.5,"stop_pct":0.02,"reward_risk":2.0}'
  --holdout-start 2023-01-01
  --holdout-end 2024-12-31
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date

from hedgefund.backtest.data import load_sp100_bars
from hedgefund.backtest.trial_log import TrialLogger
from hedgefund.backtest.validation import HoldoutEvaluator
from hedgefund.config import configure_logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# Frozen canonical params (must not change after IS search)
CANONICAL_PARAMS = {
    "breakout_lookback": 20,
    "volume_lookback": 50,
    "volume_multiplier": 1.5,
    "stop_pct": 0.02,
    "reward_risk": 2.0,
}

IS_START = date(2015, 1, 1)
IS_END = date(2022, 12, 31)
HOLDOUT_START = date(2023, 1, 1)
HOLDOUT_END = date(2024, 12, 31)

IS_PARTITION = f"sp100_breakout_is_{IS_START}_{IS_END}"
HOLDOUT_PARTITION = f"sp100_breakout_holdout_{HOLDOUT_START}_{HOLDOUT_END}"


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="One-shot holdout evaluation (ADR-0008)")
    parser.add_argument(
        "--confirm-holdout-touch", action="store_true", required=True,
        help="Explicit acknowledgement that you are spending holdout_n."
    )
    parser.add_argument("--params", default=None, help="JSON params (default: canonical)")
    parser.add_argument("--holdout-start", default=str(HOLDOUT_START))
    parser.add_argument("--holdout-end", default=str(HOLDOUT_END))
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    params = json.loads(args.params) if args.params else CANONICAL_PARAMS
    holdout_start = date.fromisoformat(args.holdout_start)
    holdout_end = date.fromisoformat(args.holdout_end)
    use_cache = not args.no_cache

    # Check search_n so the DSR is computed correctly
    with TrialLogger() as logger:
        search_n = logger.get_search_n(IS_PARTITION)
        holdout_n = logger.increment_holdout_n(HOLDOUT_PARTITION)

    if holdout_n > 1:
        print(f"\n⚠️  WARNING: holdout_n = {holdout_n} for '{HOLDOUT_PARTITION}'.")
        print("   This holdout has been touched before.  Results are NOT trustworthy.")
        print("   Only the first evaluation (holdout_n=1) counts as evidence of edge.\n")

    log.info("=== Holdout Evaluation (ADR-0008 gate) ===")
    log.info("Params: %s", json.dumps(params))
    log.info("Holdout: %s → %s", holdout_start, holdout_end)
    log.info("search_n at IS gate: %d | holdout_n: %d", search_n, holdout_n)

    # Load data (IS + holdout for warmup)
    full_start = IS_START
    log.info("Loading bars %s → %s ...", full_start, holdout_end)
    bars = load_sp100_bars(full_start, holdout_end, use_cache=use_cache)
    log.info("Loaded %d rows", len(bars))

    evaluator = HoldoutEvaluator()
    result = evaluator.evaluate(
        bars=bars,
        params=params,
        holdout_start=holdout_start,
        holdout_end=holdout_end,
        search_n=search_n,
        holdout_n=holdout_n,
        partition_name=HOLDOUT_PARTITION,
    )

    # Persist result
    with TrialLogger() as logger:
        logger.log_holdout_eval(
            strategy_name="BreakoutStrategy",
            params=params,
            holdout_partition=HOLDOUT_PARTITION,
            holdout_n=holdout_n,
            search_n=search_n,
            annualised_sharpe=result.annualised_sharpe,
            annualised_return=result.annualised_return,
            max_drawdown=result.max_drawdown,
            psr=result.psr,
            dsr=result.dsr,
            n_trades=result.n_trades,
            passed_gate=result.passes_gate,
            notes=f"holdout_n={holdout_n} search_n={search_n}",
        )

    print("\n" + "=" * 60)
    print("HOLDOUT EVALUATION RESULT")
    print("=" * 60)
    print(f"Partition:           {result.partition_name}")
    print(f"holdout_n:           {result.holdout_n}  {'(CLEAN)' if result.holdout_n == 1 else '(CONTAMINATED)'}")
    print(f"search_n at eval:    {result.search_n_at_eval}")
    print(f"Trades in holdout:   {result.n_trades}")
    print(f"Annualised return:   {result.annualised_return:.2%}")
    print(f"Annualised Sharpe:   {result.annualised_sharpe:.3f}")
    print(f"Max drawdown:        {result.max_drawdown:.2%}")
    print(f"PSR:                 {result.psr:.3f}")
    print(f"DSR:                 {result.dsr:.3f}  (search_n={result.search_n_at_eval})")
    print(f"Gate:                {'PASS ✓  — official track record is OPEN' if result.passes_gate else 'FAIL ✗  — paper trading results do NOT count'}")
    print("=" * 60)

    if result.passes_gate:
        print("\nThe strategy clears the rigorous backtest gate.")
        print("The official paper track record is now OPEN.")
        print("Phase 3 (qualitative branch) may now be built alongside.")
    else:
        print("\nThe strategy does not clear the gate on the holdout.")
        print("The official track record remains CLOSED.")
        print("Do not modify params and re-run against this holdout.")


if __name__ == "__main__":
    main()
