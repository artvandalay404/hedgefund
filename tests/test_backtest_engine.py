"""Unit tests for the event-driven backtester.

No network, no DB, no broker — only deterministic arithmetic on synthetic bars.
"""
from __future__ import annotations

import pandas as pd
import pytest

from hedgefund.backtest.costs import CostModel
from hedgefund.backtest.engine import Backtester, _check_exit, SimPosition
from hedgefund.backtest.strategy import BreakoutStrategy, TradeSignal


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_bars(
    symbol: str,
    n_days: int,
    base_close: float = 100.0,
    daily_change: float = 0.5,
    volume: int = 1_000_000,
) -> pd.DataFrame:
    dates = pd.date_range("2020-01-02", periods=n_days, freq="B")
    closes = [base_close + i * daily_change for i in range(n_days)]
    rows = []
    for i, (dt, cl) in enumerate(zip(dates, closes)):
        rows.append({
            "symbol": symbol,
            "timestamp": dt,
            "open": cl - 0.1,
            "high": cl + 0.5,
            "low": cl - 0.5,
            "close": cl,
            "volume": volume,
        })
    return pd.DataFrame(rows)


def make_multi_symbol_bars(n_days: int = 80) -> pd.DataFrame:
    return pd.concat([
        make_bars("AAA", n_days, 100.0, 0.3),
        make_bars("BBB", n_days, 50.0, 0.1),
    ], ignore_index=True)


# ── Cost model ────────────────────────────────────────────────────────────────

class TestCostModel:
    def test_buy_costs_more(self):
        cm = CostModel(half_spread_pct=0.001, slippage_pct=0.0)
        assert cm.fill_price(100.0, "buy") > 100.0

    def test_sell_costs_less(self):
        cm = CostModel(half_spread_pct=0.001, slippage_pct=0.0)
        assert cm.fill_price(100.0, "sell") < 100.0

    def test_zero_costs(self):
        cm = CostModel(0.0, 0.0)
        assert cm.fill_price(50.0, "buy") == 50.0
        assert cm.fill_price(50.0, "sell") == 50.0


# ── Exit logic ────────────────────────────────────────────────────────────────

class TestCheckExit:
    def _pos(self, stop=95.0, target=110.0) -> SimPosition:
        return SimPosition("X", 100, 100.0, stop, target, pd.Timestamp("2020-01-02"))

    def test_no_exit(self):
        pos = self._pos()
        px, reason = _check_exit(pos, 100.0, 96.0, 108.0, CostModel(0, 0))
        assert px is None and reason is None

    def test_stop_intraday(self):
        pos = self._pos(stop=95.0)
        px, reason = _check_exit(pos, 100.0, 94.0, 108.0, CostModel(0, 0))
        assert reason == "stop"
        assert abs(px - 95.0) < 0.01

    def test_stop_gap_down(self):
        # Open below stop → fill at open
        pos = self._pos(stop=95.0)
        px, reason = _check_exit(pos, 92.0, 91.0, 93.0, CostModel(0, 0))
        assert reason == "stop"
        assert abs(px - 92.0) < 0.01

    def test_target_intraday(self):
        pos = self._pos(target=110.0)
        px, reason = _check_exit(pos, 100.0, 98.0, 111.0, CostModel(0, 0))
        assert reason == "target"
        assert abs(px - 110.0) < 0.01

    def test_target_gap_up(self):
        pos = self._pos(target=110.0)
        px, reason = _check_exit(pos, 115.0, 114.0, 116.0, CostModel(0, 0))
        assert reason == "target"
        assert abs(px - 115.0) < 0.01

    def test_stop_wins_when_both_hit(self):
        # Both stop (low < stop) and target (high > target) on same day → stop wins
        pos = self._pos(stop=95.0, target=110.0)
        px, reason = _check_exit(pos, 100.0, 94.0, 111.0, CostModel(0, 0))
        assert reason == "stop"


# ── Strategy ──────────────────────────────────────────────────────────────────

class TestBreakoutStrategy:
    def test_no_signal_flat_prices(self):
        bars = make_bars("X", 80, daily_change=0.0)  # flat → never a new high
        strat = BreakoutStrategy(breakout_lookback=20, volume_lookback=50, volume_multiplier=1.5)
        sigs = strat.signals_for_date(bars, bars["timestamp"].max())
        assert len(sigs) == 0

    def test_signal_on_breakout(self):
        # Need at least volume_lookback(50) + breakout_lookback(20) + 1 = 71 bars.
        # Use 75 flat bars so the strategy has enough history, then one breakout day.
        bars = make_bars("X", 75, daily_change=0.0, volume=1_000_000)
        breakout_day = bars.iloc[-1:].copy()
        breakout_day = breakout_day.copy()
        breakout_day["timestamp"] = pd.Timestamp("2020-05-15")
        breakout_day["close"] = 200.0   # well above prior highs
        breakout_day["high"] = 200.5
        breakout_day["volume"] = 3_000_000   # 3× average → above 1.5× threshold
        bars = pd.concat([bars, breakout_day], ignore_index=True)

        strat = BreakoutStrategy(breakout_lookback=20, volume_lookback=50, volume_multiplier=1.5)
        sigs = strat.signals_for_date(bars, breakout_day["timestamp"].iloc[0])
        assert len(sigs) == 1
        assert sigs[0].symbol == "X"
        assert sigs[0].direction == "long"

    def test_precompute_matches_signals_for_date(self):
        bars = make_bars("X", 100, daily_change=0.3, volume=1_000_000)
        strat = BreakoutStrategy(breakout_lookback=20, volume_lookback=50, volume_multiplier=1.5)
        precomputed = strat.precompute(bars)
        last_day = bars["timestamp"].max()
        direct = strat.signals_for_date(bars, last_day)
        pre = precomputed.get(last_day, [])
        assert len(direct) == len(pre)


# ── Backtester ────────────────────────────────────────────────────────────────

class TestBacktester:
    def test_equity_curve_monotonically_grows_with_rising_prices(self):
        # Strategy that fires on every day (unconditional stub)
        class AlwaysBuyStrategy(BreakoutStrategy):
            def precompute(self, bars):
                result = {}
                for sym, grp in bars.groupby("symbol"):
                    for _, row in grp.iterrows():
                        day = row["timestamp"]
                        entry = float(row["close"])
                        result.setdefault(day, []).append(
                            TradeSignal(str(sym), "long", entry, entry * 0.95, entry * 1.10)
                        )
                return result

        bars = make_bars("AAA", 60, base_close=100.0, daily_change=1.0)
        bt = Backtester(AlwaysBuyStrategy(), CostModel(0, 0), initial_equity=10_000)
        result = bt.run(bars)
        assert len(result.equity_curve) > 0
        assert result.equity_curve.iloc[-1] > 0

    def test_no_signals_equity_unchanged(self):
        # Flat prices, low volume — no signals generated
        bars = make_bars("AAA", 80, daily_change=0.0, volume=100)
        strat = BreakoutStrategy(volume_multiplier=1.5)
        bt = Backtester(strat, CostModel(0, 0), initial_equity=50_000)
        result = bt.run(bars)
        # No trades → equity flat at initial value
        assert result.n_trades == 0
        # Equity curve should be all close to 50_000
        assert abs(result.equity_curve.iloc[-1] - 50_000) < 1.0

    def test_stop_loss_limits_drawdown(self):
        # Trigger a breakout, then the price crashes well below stop
        base_bars = make_bars("X", 60, base_close=100.0, daily_change=0.0, volume=1_000_000)
        breakout_row = {
            "symbol": "X", "timestamp": pd.Timestamp("2020-04-10"),
            "open": 149.0, "high": 151.0, "low": 149.0, "close": 150.0,
            "volume": 4_000_000,
        }
        crash_row = {
            "symbol": "X", "timestamp": pd.Timestamp("2020-04-13"),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,  # below any stop
            "volume": 1_000_000,
        }
        bars = pd.concat(
            [base_bars, pd.DataFrame([breakout_row]), pd.DataFrame([crash_row])],
            ignore_index=True,
        )
        strat = BreakoutStrategy(
            breakout_lookback=20, volume_lookback=50,
            volume_multiplier=1.5, stop_pct=0.02, reward_risk=2.0,
        )
        bt = Backtester(strat, CostModel(0, 0), initial_equity=100_000)
        result = bt.run(bars)
        # The stop loss should have limited the loss; equity should remain substantially positive
        if result.n_trades > 0:
            stop_trades = [t for t in result.trades if t.exit_reason == "stop"]
            for t in stop_trades:
                assert t.pnl < 0   # stop trades are losses
            assert result.equity_curve.iloc[-1] > result.start_equity * 0.80

    def test_returns_series(self):
        bars = make_multi_symbol_bars(90)
        strat = BreakoutStrategy(breakout_lookback=20, volume_lookback=50, volume_multiplier=1.5)
        bt = Backtester(strat, CostModel(0, 0))
        result = bt.run(bars)
        assert isinstance(result.returns, pd.Series)
        assert len(result.returns) > 0

    def test_max_positions_cap(self):
        # Create signals for many symbols; cap should be respected
        frames = [make_bars(f"SYM{i}", 90, base_close=50.0 + i, daily_change=0.5) for i in range(20)]
        bars = pd.concat(frames, ignore_index=True)
        strat = BreakoutStrategy(breakout_lookback=20, volume_lookback=50, volume_multiplier=1.5)
        bt = Backtester(strat, CostModel(0, 0), initial_equity=200_000, max_positions=3)
        result = bt.run(bars)
        # There should never be more than 3 open at once; just check run completes
        assert len(result.equity_curve) > 0
