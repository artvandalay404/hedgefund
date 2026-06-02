"""Strategy interface and the volume-confirmed breakout implementation.

The BreakoutStrategy parameters mirror the live scanner (pipeline/signals.py)
so that Phase 2 validates exactly what Phase 1 trades.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass

import pandas as pd


@dataclass
class TradeSignal:
    symbol: str
    direction: str        # "long" (short deferred to Phase 2+)
    entry_price: float    # yesterday's close; filled at next open
    stop_price: float
    target_price: float


class StrategyBase(ABC):
    @abstractmethod
    def signals_for_date(
        self, bars: pd.DataFrame, as_of: pd.Timestamp
    ) -> list[TradeSignal]:
        """Return signals generated at end of `as_of` (point-in-time safe)."""

    def precompute(self, bars: pd.DataFrame) -> dict[pd.Timestamp, list[TradeSignal]]:
        """Vectorised pre-computation of all signals across all dates.

        Default delegates to signals_for_date per day. Subclasses override
        for efficiency with rolling windows.
        """
        result: dict[pd.Timestamp, list[TradeSignal]] = defaultdict(list)
        for day in sorted(bars["timestamp"].unique()):
            hist = bars[bars["timestamp"] <= day]
            for sig in self.signals_for_date(hist, day):
                result[day].append(sig)
        return dict(result)


class BreakoutStrategy(StrategyBase):
    """Volume-confirmed breakout: new N-day high + volume > M × trailing average.

    Matches the Phase 1 scanner in pipeline/signals.py exactly so the
    backtester validates the same signal that will be traded live.
    """

    def __init__(
        self,
        breakout_lookback: int = 20,
        volume_lookback: int = 50,
        volume_multiplier: float = 1.5,
        stop_pct: float = 0.02,
        reward_risk: float = 2.0,
    ):
        self.breakout_lookback = breakout_lookback
        self.volume_lookback = volume_lookback
        self.volume_multiplier = volume_multiplier
        self.stop_pct = stop_pct
        self.reward_risk = reward_risk

    @property
    def params(self) -> dict:
        return {
            "breakout_lookback": self.breakout_lookback,
            "volume_lookback": self.volume_lookback,
            "volume_multiplier": self.volume_multiplier,
            "stop_pct": self.stop_pct,
            "reward_risk": self.reward_risk,
        }

    def signals_for_date(
        self, bars: pd.DataFrame, as_of: pd.Timestamp
    ) -> list[TradeSignal]:
        hist = bars[bars["timestamp"] <= as_of]
        return self._scan(hist)

    def _scan(self, hist: pd.DataFrame) -> list[TradeSignal]:
        results: list[TradeSignal] = []
        for symbol, grp in hist.groupby("symbol"):
            grp = grp.sort_values("timestamp")
            required = self.volume_lookback + self.breakout_lookback + 1
            if len(grp) < required:
                continue
            last = grp.iloc[-1]
            prior_high = grp.iloc[-self.breakout_lookback - 1: -1]["high"].max()
            avg_vol = grp.iloc[-self.volume_lookback - 1: -1]["volume"].mean()
            if avg_vol <= 0:
                continue
            if float(last["close"]) > float(prior_high) and \
               float(last["volume"]) > avg_vol * self.volume_multiplier:
                entry = float(last["close"])
                stop = entry * (1 - self.stop_pct)
                target = entry + self.reward_risk * (entry - stop)
                results.append(TradeSignal(str(symbol), "long", entry, stop, target))
        return results

    def precompute(self, bars: pd.DataFrame) -> dict[pd.Timestamp, list[TradeSignal]]:
        """Vectorised rolling-window computation — O(N) vs O(N²) naive loop."""
        result: dict[pd.Timestamp, list[TradeSignal]] = {}
        for day in sorted(bars["timestamp"].unique()):
            result[day] = []

        for symbol, grp in bars.groupby("symbol"):
            grp = grp.sort_values("timestamp").reset_index(drop=True)
            # shift(1) so today's data is excluded from the lookback window
            roll_high = grp["high"].shift(1).rolling(self.breakout_lookback).max()
            avg_vol = grp["volume"].shift(1).rolling(self.volume_lookback).mean()
            is_high = grp["close"] > roll_high
            is_vol = grp["volume"] > avg_vol * self.volume_multiplier
            signal_mask = is_high & is_vol

            for idx in grp[signal_mask].index:
                row = grp.loc[idx]
                day = row["timestamp"]
                entry = float(row["close"])
                stop = entry * (1 - self.stop_pct)
                target = entry + self.reward_risk * (entry - stop)
                if day in result:
                    result[day].append(
                        TradeSignal(str(symbol), "long", entry, stop, target)
                    )

        return result
