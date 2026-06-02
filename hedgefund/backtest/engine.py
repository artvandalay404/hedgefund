"""Event-driven daily-bar backtester.

Design principles (ADR-0003, ADR-0005, ADR-0007):
- Point-in-time: signals are generated at end of day T, fills at T+1 open.
- Honest stop modeling: gap-down below stop → fill at open, not stop.
- Cost model: half-spread + slippage on every fill.
- Sizing mirrors the live risk module (ADR-0004): fixed-fractional with
  all the same caps (position count, notional, portfolio heat).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from hedgefund.backtest.costs import CostModel
from hedgefund.backtest.strategy import StrategyBase, TradeSignal


@dataclass
class SimPosition:
    symbol: str
    qty: int
    entry_price: float    # actual fill price (post-cost)
    stop_price: float
    target_price: float
    entry_date: pd.Timestamp


@dataclass
class TradeRecord:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: int
    pnl: float
    exit_reason: str   # stop | target | eod_liquidation


@dataclass
class BacktestResult:
    equity_curve: pd.Series          # date → total equity
    trades: list[TradeRecord]
    start_equity: float

    @property
    def returns(self) -> pd.Series:
        """Daily arithmetic returns."""
        return self.equity_curve.pct_change().dropna()

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades) if self.trades else float("nan")


class Backtester:
    def __init__(
        self,
        strategy: StrategyBase,
        costs: Optional[CostModel] = None,
        initial_equity: float = 100_000.0,
        risk_per_trade: float = 0.005,
        max_positions: int = 8,
        max_notional_pct: float = 0.15,
        max_heat: float = 0.04,
    ):
        self.strategy = strategy
        self.costs = costs or CostModel()
        self.initial_equity = initial_equity
        self.risk_per_trade = risk_per_trade
        self.max_positions = max_positions
        self.max_notional_pct = max_notional_pct
        self.max_heat = max_heat

    def run(self, bars: pd.DataFrame) -> BacktestResult:
        """Run the backtest on a bar DataFrame.

        bars must have columns: symbol, timestamp, open, high, low, close, volume.
        Timestamps are treated as date-level (time component ignored).
        """
        bars = bars.copy()
        bars["timestamp"] = pd.to_datetime(bars["timestamp"]).dt.tz_localize(None).dt.normalize()

        # Precompute all signals once (vectorised O(N) over symbols)
        all_signals: dict[pd.Timestamp, list[TradeSignal]] = self.strategy.precompute(bars)

        trading_days = sorted(bars["timestamp"].unique())
        cash = self.initial_equity
        positions: dict[str, SimPosition] = {}
        trades: list[TradeRecord] = []
        equity_curve: dict[pd.Timestamp, float] = {}
        pending: list[TradeSignal] = []   # signals from prior day, fill at today's open

        for day in trading_days:
            day_slice = bars[bars["timestamp"] == day].set_index("symbol")

            # A. Fill pending entries at today's open
            remaining_pending: list[TradeSignal] = []
            for sig in pending:
                if sig.symbol not in day_slice.index:
                    continue
                if sig.symbol in positions:
                    continue
                if len(positions) >= self.max_positions:
                    break

                open_px = float(day_slice.loc[sig.symbol, "open"])
                fill_px = self.costs.fill_price(open_px, "buy")

                qty = self._compute_qty(cash, positions, day_slice, fill_px, sig)
                if qty <= 0:
                    continue

                cash -= qty * fill_px
                positions[sig.symbol] = SimPosition(
                    symbol=sig.symbol,
                    qty=qty,
                    entry_price=fill_px,
                    stop_price=sig.stop_price,
                    target_price=sig.target_price,
                    entry_date=day,
                )

            pending = []   # consumed

            # B. Check exits for all open positions
            closed: list[str] = []
            for sym, pos in positions.items():
                if sym not in day_slice.index:
                    continue
                row = day_slice.loc[sym]
                exit_px, reason = _check_exit(
                    pos,
                    float(row["open"]),
                    float(row["low"]),
                    float(row["high"]),
                    self.costs,
                )
                if exit_px is not None:
                    cash += pos.qty * exit_px
                    trades.append(TradeRecord(
                        symbol=sym,
                        entry_date=pos.entry_date,
                        exit_date=day,
                        entry_price=pos.entry_price,
                        exit_price=exit_px,
                        qty=pos.qty,
                        pnl=pos.qty * (exit_px - pos.entry_price),
                        exit_reason=reason,
                    ))
                    closed.append(sym)

            for sym in closed:
                del positions[sym]

            # C. Mark total equity at end of day
            pos_value = sum(
                p.qty * float(day_slice.loc[p.symbol, "close"])
                for p in positions.values()
                if p.symbol in day_slice.index
            )
            equity_curve[day] = cash + pos_value

            # D. Queue tomorrow's entries (signals generated at end of today)
            pending = all_signals.get(day, [])

        # Liquidate any remaining open positions at last known close
        if positions:
            last_day = trading_days[-1]
            last_slice = bars[bars["timestamp"] == last_day].set_index("symbol")
            for sym, pos in positions.items():
                if sym not in last_slice.index:
                    continue
                close_px = self.costs.fill_price(float(last_slice.loc[sym, "close"]), "sell")
                cash += pos.qty * close_px
                trades.append(TradeRecord(
                    symbol=sym,
                    entry_date=pos.entry_date,
                    exit_date=last_day,
                    entry_price=pos.entry_price,
                    exit_price=close_px,
                    qty=pos.qty,
                    pnl=pos.qty * (close_px - pos.entry_price),
                    exit_reason="eod_liquidation",
                ))
            equity_curve[last_day] = cash

        return BacktestResult(
            equity_curve=pd.Series(equity_curve),
            trades=trades,
            start_equity=self.initial_equity,
        )

    def _compute_qty(
        self,
        cash: float,
        positions: dict[str, SimPosition],
        day_slice: pd.DataFrame,
        fill_price: float,
        sig: TradeSignal,
    ) -> int:
        # Total equity for sizing purposes
        pos_mark = sum(
            p.qty * float(day_slice.loc[p.symbol, "close"])
            for p in positions.values()
            if p.symbol in day_slice.index
        )
        equity = cash + pos_mark

        distance = fill_price - sig.stop_price
        if distance <= 0:
            return 0

        risk_budget = equity * self.risk_per_trade
        qty = int(risk_budget / distance)
        if qty <= 0:
            return 0

        # Notional cap
        max_notional = equity * self.max_notional_pct
        qty = min(qty, int(max_notional / fill_price))

        # Portfolio heat cap (open risk from existing positions)
        heat = sum(
            p.qty * max(0.0, float(day_slice.loc[p.symbol, "close"]) - p.stop_price)
            for p in positions.values()
            if p.symbol in day_slice.index
        )
        remaining_heat = equity * self.max_heat - heat
        if remaining_heat <= 0:
            return 0
        trade_risk = qty * distance
        if trade_risk > remaining_heat:
            qty = int(remaining_heat / distance)

        return max(0, qty)


def _check_exit(
    pos: SimPosition,
    day_open: float,
    day_low: float,
    day_high: float,
    costs: CostModel,
) -> tuple[Optional[float], Optional[str]]:
    """Return (fill_price, reason) or (None, None) if no exit today.

    Priority: gap-down stop > intraday stop > gap-up target > intraday target.
    Stop priority on same-day stop+target ambiguity (conservative).
    """
    # Gap down through stop — fill at open (worse than stop)
    if day_open <= pos.stop_price:
        return costs.fill_price(day_open, "sell"), "stop"
    # Intraday stop hit
    if day_low <= pos.stop_price:
        return costs.fill_price(pos.stop_price, "sell"), "stop"
    # Gap up through target — fill at open (better than target)
    if day_open >= pos.target_price:
        return costs.fill_price(day_open, "sell"), "target"
    # Intraday target hit
    if day_high >= pos.target_price:
        return costs.fill_price(pos.target_price, "sell"), "target"
    return None, None
