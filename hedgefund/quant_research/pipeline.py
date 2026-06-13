"""The deterministic authoring pipeline (ADR-0009, issue #28).

Given an *already-authored* StrategySpec and a bar history, run everything
downstream of the LLM: neighbourhood generation, walk-forward CV,
neighbourhood effective-N, trial logging, and report assembly.

The LLM authoring step and data loading stay in the caller
(scripts/author_strategy.py) so this module is pure deterministic code — it can
be exercised end-to-end in tests with a synthetic spec and an in-memory trial
log, with no Anthropic call and no real DB.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import pandas as pd

from hedgefund.backtest.trial_log import TrialLogger
from hedgefund.backtest.validation import WalkForwardCV, WalkForwardResult
from hedgefund.quant_research.compiler import compile_spec
from hedgefund.quant_research.dsl import StrategySpec
from hedgefund.quant_research.neighborhood import (
    generate_neighborhood,
    participation_ratio,
)
from hedgefund.quant_research.report import AuthoringReport

log = logging.getLogger(__name__)


@dataclass
class AuthoringRun:
    """Everything one authoring pass produces (besides the trial-log writes)."""
    spec: StrategySpec
    neighbors: list[StrategySpec]
    wf_result: WalkForwardResult
    neighborhood_effective_n: float
    cumulative_search_n: float
    report: AuthoringReport


def run_authoring(
    spec: StrategySpec,
    bars: pd.DataFrame,
    *,
    trial_logger: TrialLogger,
    partition: str,
    cv: WalkForwardCV | None = None,
) -> AuthoringRun:
    """Backtest a StrategySpec walk-forward, log trials, and build the report.

    The caller supplies the (already-authored) spec, the bar history, and an
    entered TrialLogger.  ``cv`` defaults to the rigorous-backtest window
    (6-month OOS folds, 24-month minimum train, 10-day embargo).

    Raises ValueError if the data range yields no completed folds.
    """
    if cv is None:
        cv = WalkForwardCV(test_months=6, min_train_months=24, embargo_days=10)

    # ── Canonical + neighbourhood configs (ADR-0010 §3) ─────────────────────
    neighbors = generate_neighborhood(spec)
    all_specs = [spec] + neighbors
    log.info(
        "Canonical + %d neighbors = %d configs total",
        len(neighbors), len(all_specs),
    )

    spec_map = {
        json.dumps(s.config_identity(), sort_keys=True): compile_spec(s)
        for s in all_specs
    }
    all_configs = [s.config_identity() for s in all_specs]

    def factory(cfg: dict):
        return spec_map[json.dumps(cfg, sort_keys=True)]

    # ── Walk-forward CV over all configs ────────────────────────────────────
    log.info("Running walk-forward CV over %d configs...", len(all_configs))
    wf_result = cv.run(bars, all_configs, strategy_factory=factory)
    if not wf_result.folds:
        raise ValueError("No folds completed — insufficient data range.")

    n_folds = len({f.fold_name for f in wf_result.folds})
    log.info(
        "%d folds × %d configs = %d fold-results",
        n_folds, len(all_configs), len(wf_result.folds),
    )

    # ── Neighbourhood effective-N — diagnostic only (ADR-0010 §3, amended) ──
    # The participation ratio no longer *charges* the counter; it is a reported
    # guardrail confirming the harness neighbour family really is ~1 bet (an
    # eff-N well above 1 means the "robustness neighbourhood" isn't tight).  The
    # machinery stays load-bearing for #26's population-wide accrual.
    config_returns: dict[str, list[float]] = {}
    for fold in wf_result.folds:
        key = json.dumps(fold.params, sort_keys=True)
        config_returns.setdefault(key, []).extend(fold.oos_returns)
    eff_n = participation_ratio(list(config_returns.values()))

    # ── Charge the partition exactly ONE trial (ADR-0010 §3, amended) ───────
    # The canonical spec, its ±1-step neighbour variants, and the walk-forward
    # folds are *one bet, not N*: neighbours are a robustness check and folds are
    # CV slices of a single evaluation.  So search_n moves by 1 per authoring
    # run.  Every fold-result is still logged for the audit trail, all stamped
    # with this one search_n.
    sn = trial_logger.increment_search_n(partition)
    for fold in wf_result.folds:
        trial_logger.log_trial(
            strategy_name=f"DSL:{spec.name}",
            params=fold.params,
            partition_name=partition,
            search_n=sn,
            annualised_sharpe=fold.oos_sharpe,
            annualised_return=fold.oos_return,
            max_drawdown=fold.oos_max_dd,
            n_trades=fold.oos_n_trades,
            returns=fold.oos_returns,
        )
    cumulative_sn = float(trial_logger.get_search_n(partition))

    # ── Build report ─────────────────────────────────────────────────────────
    summary = wf_result.summary(n_trials=cumulative_sn)
    status = (
        "FROZEN — eligible for holdout"
        if summary["passes_gate"]
        else "FAIL — refine in-sample"
    )
    report = AuthoringReport(
        spec=spec,
        wf_summary=summary,
        neighborhood_effective_n=eff_n,
        cumulative_search_n=cumulative_sn,
        passes_gate=summary["passes_gate"],
        status=status,
    )

    return AuthoringRun(
        spec=spec,
        neighbors=neighbors,
        wf_result=wf_result,
        neighborhood_effective_n=eff_n,
        cumulative_search_n=cumulative_sn,
        report=report,
    )
