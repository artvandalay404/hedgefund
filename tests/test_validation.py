"""Walk-forward summary DSR deflation (ADR-0008 §2/§4, ADR-0010 §3).

summary() deflates its in-sample DSR by the multiple-comparisons count N it is
handed — the per-partition search-N when a caller has it — and *never* by the
fold-result count.  Folds are CV slices of a single config, not trials, so they
must not inflate N.  Synthetic FoldResults only — no bars, no DB.
"""
from __future__ import annotations

from hedgefund.backtest.validation import FoldResult, WalkForwardResult


def _wf_result() -> WalkForwardResult:
    """3 configs × 2 folds; config p=1 is best IS (and best OOS)."""
    configs = [{"p": 1}, {"p": 2}, {"p": 3}]
    oos = {1: 2.0, 2: 1.0, 3: 0.5}
    is_ = {1: 2.5, 2: 1.2, 3: 0.4}      # p=1 is best in-sample → selected
    folds = []
    for cfg in configs:
        p = cfg["p"]
        for i, fold_name in enumerate(("foldA", "foldB")):
            folds.append(FoldResult(
                fold_name=fold_name,
                is_sharpe=is_[p],
                oos_sharpe=oos[p] + (0.05 if i else -0.05),  # within-config CV spread
                oos_return=0.1,
                oos_max_dd=-0.1,
                oos_n_trades=10,
                params=cfg,
                oos_returns=[0.01, -0.01, 0.02],
            ))
    return WalkForwardResult(folds=folds, param_grid=configs)


class TestSummaryDeflation:
    def test_default_n_trials_is_distinct_config_count(self):
        s = _wf_result().summary()
        assert s["n_trials"] == 3      # configs, not 3×2 = 6 fold-results
        assert s["n_folds"] == 2       # the selected config ran in 2 folds

    def test_search_n_threads_through(self):
        assert _wf_result().summary(n_trials=42)["n_trials"] == 42

    def test_larger_search_n_deflates_more(self):
        wf = _wf_result()
        dsr_small = wf.summary(n_trials=3)["dsr"]
        dsr_large = wf.summary(n_trials=500)["dsr"]
        assert dsr_large < dsr_small

    def test_n_equals_one_gets_no_deflation(self):
        # search-N == 1 (a robustness neighbourhood charged ~1, or a single
        # fresh strategy) → DSR collapses to PSR: no multiple-comparisons hit.
        s = _wf_result().summary(n_trials=1)
        assert s["dsr"] == s["psr"]
