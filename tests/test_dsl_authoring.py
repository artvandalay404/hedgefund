"""End-to-end test of the LLM-authoring pipeline (ADR-0009, issue #28).

The real pipeline (scripts/author_strategy.py) is: PM theory → LLM authors a
StrategySpec → compile → neighbourhood → walk-forward CV → trial log → report.
Here we replace *only* the LLM authoring step with a hardcoded default spec —
the canonical volume-confirmed breakout — and exercise everything downstream on
synthetic bars and an in-memory DB.  No network, no Anthropic call, no dev.db.

Two things are asserted:
  1. The compiled DSL breakout reproduces the hand-written BreakoutStrategy
     exactly (the DSL is a faithful re-expression of v1's canonical strategy).
  2. The full author→backtest→report pipeline runs and persists trials.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from hedgefund.backtest.strategy import BreakoutStrategy
from hedgefund.backtest.trial_log import TrialLogger
from hedgefund.backtest.validation import WalkForwardCV
from hedgefund.db.models import Base, BacktestTrial, PartitionCounter
from hedgefund.quant_research.compiler import DSLStrategy, compile_spec
from hedgefund.quant_research.dsl import StrategySpec
from hedgefund.quant_research.neighborhood import generate_neighborhood
from hedgefund.quant_research.pipeline import run_authoring


# ── The default DSL spec (stands in for the LLM author) ─────────────────────────

def default_breakout_spec() -> StrategySpec:
    """v1's canonical volume-confirmed breakout, expressed in the DSL.

    Mirror of BreakoutStrategy(breakout_lookback=20, volume_lookback=50,
    volume_multiplier=1.5, stop_pct=0.02, reward_risk=2.0):
        entry: close > rolling_high(20) AND volume > avg_volume(50) * 1.5
        exit:  stop = 2% below entry, target at 2R
    """
    return StrategySpec.model_validate({
        "name": "volume_confirmed_breakout",
        "direction": "long",
        "entry": {
            "logic": "AND",
            "predicates": [
                {
                    "lhs": {"primitive": {"name": "close"}, "scale": 1.0},
                    "op": ">",
                    "rhs": {"primitive": {"name": "rolling_high", "period": 20}, "scale": 1.0},
                },
                {
                    "lhs": {"primitive": {"name": "volume"}, "scale": 1.0},
                    "op": ">",
                    "rhs": {"primitive": {"name": "avg_volume", "period": 50}, "scale": 1.5},
                },
            ],
        },
        "exit": {"stop": {"kind": "percent", "value": 0.02}, "reward_risk": 2.0},
        "rationale": {
            "mechanism": "Breakouts on heavy volume mark institutional accumulation "
                         "that tends to continue over a swing horizon.",
            "why_not_arbitraged": "Capacity-limited and noisy at the single-name level; "
                                  "large funds can't lean on it without moving price.",
            "what_would_break_it": "A persistently mean-reverting, low-dispersion regime "
                                   "where breakouts fail back into the range.",
            "known_anomaly_disclosure": "Maps to time-series momentum / 52-week-high "
                                        "(George & Hwang 2004).",
        },
    })


# The reference hand-written strategy the spec is supposed to reproduce.
def reference_breakout() -> BreakoutStrategy:
    return BreakoutStrategy(
        breakout_lookback=20, volume_lookback=50,
        volume_multiplier=1.5, stop_pct=0.02, reward_risk=2.0,
    )


# ── Synthetic-bar helpers ───────────────────────────────────────────────────────

def make_flat_bars(symbol: str, n_days: int, close: float = 100.0,
                   volume: int = 1_000_000) -> pd.DataFrame:
    dates = pd.date_range("2020-01-02", periods=n_days, freq="B")
    rows = [{
        "symbol": symbol, "timestamp": dt,
        "open": close - 0.1, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": volume,
    } for dt in dates]
    return pd.DataFrame(rows)


def make_uptrend_bars(symbol: str, n_days: int, base: float = 100.0,
                      drift: float = 1.0, base_vol: int = 1_000_000,
                      spike_every: int = 10, spike_mult: float = 3.0,
                      start: str = "2018-01-02") -> pd.DataFrame:
    """Steady uptrend (every day a new 20-day high) with periodic volume spikes.

    drift > 0.5 guarantees close beats the prior 20-day high (high = close + 0.5),
    so breakout signals fire on the volume-spike days once history is long enough
    for both the rolling_high(20) and avg_volume(50) windows (index >= 50).
    """
    dates = pd.date_range(start, periods=n_days, freq="B")
    rows = []
    for i, dt in enumerate(dates):
        cl = base + drift * i
        is_spike = spike_every and i >= 51 and i % spike_every == 0
        rows.append({
            "symbol": symbol, "timestamp": dt,
            "open": cl - 0.1, "high": cl + 0.5, "low": cl - 0.5,
            "close": cl, "volume": int(base_vol * (spike_mult if is_spike else 1.0)),
        })
    return pd.DataFrame(rows)


def _sig_map(precomputed: dict) -> dict:
    """Flatten a precompute() result into a comparable {day: [(sym, e, s, t)]}."""
    out: dict = {}
    for day, sigs in precomputed.items():
        if not sigs:
            continue
        out[pd.Timestamp(day)] = sorted(
            (s.symbol, round(s.entry_price, 6), round(s.stop_price, 6),
             round(s.target_price, 6))
            for s in sigs
        )
    return out


@pytest.fixture
def session():
    """In-memory SQLite session — never touches the real trial-log DB."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


# ── The default spec itself ─────────────────────────────────────────────────────

class TestDefaultBreakoutSpec:
    def test_validates_and_compiles(self):
        spec = default_breakout_spec()
        strat = compile_spec(spec)
        assert isinstance(strat, DSLStrategy)
        assert strat.spec.name == "volume_confirmed_breakout"

    def test_config_identity_excludes_rationale(self):
        identity = default_breakout_spec().config_identity()
        assert set(identity) == {"name", "direction", "entry", "exit"}
        assert "rationale" not in identity


# ── Equivalence: the DSL reproduces the hand-written breakout exactly ────────────

class TestDSLReproducesBreakoutStrategy:
    def test_fires_on_crafted_breakout(self):
        # 75 flat bars, then one heavy-volume breakout day (mirrors the
        # existing engine test). Both strategies must agree on signals_for_date.
        bars = make_flat_bars("X", 75)
        breakout = bars.iloc[-1:].copy()
        breakout["timestamp"] = pd.Timestamp("2020-05-15")
        breakout["close"] = 200.0
        breakout["high"] = 200.5
        breakout["volume"] = 3_000_000
        bars = pd.concat([bars, breakout], ignore_index=True)
        as_of = breakout["timestamp"].iloc[0]

        dsl_sigs = compile_spec(default_breakout_spec()).signals_for_date(bars, as_of)
        ref_sigs = reference_breakout().signals_for_date(bars, as_of)

        assert len(dsl_sigs) == 1
        s = dsl_sigs[0]
        assert (s.symbol, s.direction) == ("X", "long")
        assert s.entry_price == pytest.approx(200.0)
        assert s.stop_price == pytest.approx(196.0)            # 2% below entry
        assert s.target_price == pytest.approx(208.0)          # entry + 2R
        # Identical to the hand-written strategy.
        assert len(ref_sigs) == 1
        r = ref_sigs[0]
        assert (s.entry_price, s.stop_price, s.target_price) == \
               pytest.approx((r.entry_price, r.stop_price, r.target_price))

    def test_precompute_matches_breakout_strategy(self):
        # Over a full uptrend with spikes, the compiled DSL must produce the
        # exact same signal set as BreakoutStrategy (same primitives, stop, RR).
        bars = make_uptrend_bars("AAA", 180, drift=1.0, spike_every=15)

        dsl = _sig_map(compile_spec(default_breakout_spec()).precompute(bars))
        ref = _sig_map(reference_breakout().precompute(bars))

        assert dsl, "expected at least one breakout signal in the fixture"
        assert dsl == ref


# ── Full pipeline: author (stubbed) → backtest → report, minus the LLM ───────────

class TestAuthoringPipelineWithoutLLM:
    PARTITION = "test_sp100_is"

    def _run_pipeline(self, session):
        """Drive the real run_authoring() — the same call scripts/
        author_strategy.py makes — with a default spec instead of the LLM,
        synthetic bars, and an in-memory trial log."""
        spec = default_breakout_spec()  # ← the only step the real script does via LLM
        bars = pd.concat([
            make_uptrend_bars("AAA", 420, base=100.0, drift=1.0, spike_every=10),
            make_uptrend_bars("BBB", 420, base=60.0, drift=0.8, spike_every=10),
        ], ignore_index=True)

        cv = WalkForwardCV(test_months=3, min_train_months=6, embargo_days=5)
        with TrialLogger(session=session) as logger:
            return run_authoring(
                spec, bars, trial_logger=logger, partition=self.PARTITION, cv=cv
            )

    def test_neighborhood_is_bounded_and_valid(self):
        spec = default_breakout_spec()
        neighbors = generate_neighborhood(spec)
        # rolling_high(20) ±5 and avg_volume(50) ±10 → 4 neighbours.
        assert len(neighbors) == 4
        assert all(isinstance(n, StrategySpec) for n in neighbors)
        # Neighbours differ from canonical only in period params.
        canon = spec.config_identity()
        assert all(n.config_identity() != canon for n in neighbors)

    def test_walkforward_produces_folds(self, session):
        run = self._run_pipeline(session)
        assert run.wf_result.folds, "walk-forward produced no folds"
        # A signal-generating fixture should actually trade somewhere.
        assert any(f.oos_n_trades > 0 for f in run.wf_result.folds)

    def test_trials_persisted_to_db(self, session):
        run = self._run_pipeline(session)

        trials = session.query(BacktestTrial).all()
        assert len(trials) == len(run.wf_result.folds)
        assert all(t.strategy_name == f"DSL:{run.spec.name}" for t in trials)
        # Every persisted params_json is one of the evaluated config identities.
        valid_keys = {json.dumps(s.config_identity(), sort_keys=True)
                      for s in [run.spec] + run.neighbors}
        for t in trials:
            assert json.dumps(json.loads(t.params_json), sort_keys=True) in valid_keys

        # Every fold-result is logged for the audit trail, but the partition is
        # charged exactly ONE trial per authoring run — folds and neighbour
        # variants are one bet, not N (ADR-0010 §3, amended).
        counter = (
            session.query(PartitionCounter)
            .filter_by(partition_name=self.PARTITION)
            .one()
        )
        assert counter.search_n == 1
        assert counter.holdout_n == 0          # holdout never touched here

    def test_effective_n_within_bounds(self, session):
        run = self._run_pipeline(session)
        k = 1 + len(run.neighbors)
        assert 1.0 <= run.neighborhood_effective_n <= k + 1e-9

    def test_report_renders(self, session, capsys):
        run = self._run_pipeline(session)
        summary = run.report.wf_summary
        for key in ("oos_mean_sharpe", "psr", "dsr", "pbo", "passes_gate", "n_folds"):
            assert key in summary

        run.report.print_report()
        out = capsys.readouterr().out
        assert "AUTHORING REPORT" in out
        assert run.spec.name in out
        assert "Gate:" in out
        assert ("PASS" in out or "FAIL" in out)
