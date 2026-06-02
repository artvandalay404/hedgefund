"""Volume-confirmed breakout signal scanner (Phase 1 / plumbing version).

Phase 2 will subject this exact logic to rigorous walk-forward + holdout
validation before the official track record opens (ADR-0003, ADR-0007).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import structlog

from hedgefund.config import settings as _cfg

log = structlog.get_logger(__name__)


@dataclass
class RawSignal:
    symbol: str
    direction: str              # long (short deferred to Phase 2+)
    entry_price: float          # prior close — filled at market open
    stop_price: float
    target_price: float
    branch: str = "quant"


def scan_breakouts(bars_df: pd.DataFrame) -> list[RawSignal]:
    """Return long breakout signals from yesterday's bars.

    Entry condition (Phase 1):
      - Yesterday's close is a new N-day high
      - Yesterday's volume is > 1.5× the 50-day trailing average
    Exit levels:
      - Stop  : entry × (1 − stop_pct)
      - Target: entry + reward_risk × (entry − stop)
    """
    if bars_df.empty:
        return []

    cfg = _cfg
    signals: list[RawSignal] = []

    # Normalise column names alpaca-py may vary
    df = bars_df.copy()
    if "symbol" not in df.columns:
        log.warning("signals.missing_symbol_column")
        return []

    for symbol, group in df.groupby("symbol"):
        group = group.sort_values("timestamp").reset_index(drop=True)

        required = cfg.volume_lookback + 2
        if len(group) < required:
            continue

        # Use all rows except the last one (today — market not yet open)
        history = group.iloc[:-1]
        last = history.iloc[-1]

        # N-day high: compare last close against prior N days (excluding last)
        lookback_window = history.iloc[-cfg.breakout_lookback - 1:-1]
        if lookback_window.empty:
            continue
        prior_high = lookback_window["high"].max()

        # Volume: compare last volume against trailing average
        vol_window = history.iloc[-cfg.volume_lookback - 1:-1]
        avg_volume = vol_window["volume"].mean() if not vol_window.empty else 0

        if avg_volume <= 0:
            continue

        is_new_high = float(last["close"]) > float(prior_high)
        is_high_volume = float(last["volume"]) > avg_volume * cfg.volume_multiplier

        if is_new_high and is_high_volume:
            entry = round(float(last["close"]), 2)
            stop = round(entry * (1.0 - cfg.stop_pct), 2)
            target = round(entry + cfg.reward_risk * (entry - stop), 2)
            signals.append(
                RawSignal(
                    symbol=str(symbol),
                    direction="long",
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                )
            )
            log.debug(
                "signal.found",
                symbol=symbol,
                entry=entry,
                stop=stop,
                target=target,
                vol_ratio=round(float(last["volume"]) / avg_volume, 2),
            )

    log.info("signals.scan_complete", count=len(signals))
    return signals
