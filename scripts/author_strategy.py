#!/usr/bin/env python
"""PM theory → DSL spec → walk-forward report (ADR-0009, issue #28).

One human-triggered invocation per theory.  No autonomous loop, no holdout touch.

Usage:
  python scripts/author_strategy.py --theory "momentum breakout after RSI reset"
  python scripts/author_strategy.py --theory "..." --start 2015-01-01 --end 2022-12-31
  python scripts/author_strategy.py --theory "..." --no-cache
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date

from hedgefund.backtest.data import load_sp100_bars
from hedgefund.backtest.trial_log import TrialLogger
from hedgefund.config import configure_logging
from hedgefund.quant_research.author import author_strategy
from hedgefund.quant_research.pipeline import run_authoring

DEFAULT_IS_START = date(2015, 1, 1)
DEFAULT_IS_END = date(2022, 12, 31)
DEFAULT_PARTITION = "sp100_is_2015_2022"

log = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Author a strategy from a PM theory")
    parser.add_argument("--theory", required=True, help="Natural-language trading theory")
    parser.add_argument("--start", default=str(DEFAULT_IS_START))
    parser.add_argument("--end", default=str(DEFAULT_IS_END))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--partition", default=DEFAULT_PARTITION)
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    # ── Step 1: Author spec via LLM ─────────────────────────────────────────
    log.info("Authoring strategy spec from theory...")
    spec = author_strategy(args.theory)
    print("\nSpec authored:")
    print(json.dumps(json.loads(spec.model_dump_json(by_alias=True)), indent=2))

    # ── Step 2: Load IS data ─────────────────────────────────────────────────
    log.info("Loading S&P 100 bars (%s → %s)...", start, end)
    bars = load_sp100_bars(start, end, use_cache=not args.no_cache)
    if bars.empty:
        log.error("No bars loaded — check data fetch or cache.")
        return

    # ── Step 3: Backtest, account, and report (deterministic pipeline) ───────
    try:
        with TrialLogger() as logger:
            run = run_authoring(
                spec, bars, trial_logger=logger, partition=args.partition
            )
    except ValueError as exc:
        log.error("%s", exc)
        return

    run.report.print_report()


if __name__ == "__main__":
    main()
