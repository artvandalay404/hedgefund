"""Historical bar loader for backtesting.

Uses yfinance (free, no API key, 20+ years of history) rather than Alpaca so
that backtesting has no external credential dependency.  Results are cached to
~/.hedgefund/cache/ as Parquet files to avoid redundant network calls.

Note on survivorship bias: we use the current S&P 100 snapshot throughout the
backtest period.  This introduces upward bias because we only test on stocks
that survived into the index.  The bias is documented; sourcing point-in-time
historical membership is a future improvement (tracked in ADR-0005 open item).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from hedgefund.data.universe import SP100

_logger = logging.getLogger(__name__)

_CACHE_DIR = Path(os.environ.get("HEDGEFUND_CACHE_DIR", Path.home() / ".hedgefund" / "cache"))
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_key(symbols: list[str], start: date, end: date) -> str:
    payload = json.dumps(sorted(symbols) + [str(start), str(end)], sort_keys=True)
    return hashlib.md5(payload.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.parquet"


def load_bars(
    symbols: list[str],
    start: date,
    end: date,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Return daily OHLCV bars for `symbols` from `start` to `end`.

    Returns a DataFrame with columns:
      symbol, timestamp, open, high, low, close, volume
    timestamp is a timezone-naive date-level Timestamp.
    """
    key = _cache_key(symbols, start, end)
    path = _cache_path(key)

    if use_cache and path.exists():
        _logger.info("data.cache_hit path=%s", path)
        return pd.read_parquet(path)

    _logger.info("data.fetch symbols=%d start=%s end=%s", len(symbols), start, end)

    raw = yf.download(
        tickers=symbols,
        start=str(start),
        end=str(end),
        interval="1d",
        auto_adjust=True,       # adjust for splits + dividends
        progress=False,
        threads=True,
    )

    if raw.empty:
        return pd.DataFrame(columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])

    # yfinance with multiple tickers returns a MultiIndex on columns
    if isinstance(raw.columns, pd.MultiIndex):
        frames = []
        for sym in symbols:
            try:
                df = raw.xs(sym, axis=1, level=1).copy()
            except KeyError:
                continue
            df.columns = [c.lower() for c in df.columns]
            df["symbol"] = sym
            df = df.reset_index().rename(columns={"Date": "timestamp", "index": "timestamp"})
            frames.append(df)
        result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    else:
        # Single ticker
        raw.columns = [c.lower() for c in raw.columns]
        raw["symbol"] = symbols[0]
        result = raw.reset_index().rename(columns={"Date": "timestamp", "index": "timestamp"})

    if result.empty:
        return pd.DataFrame(columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])

    result["timestamp"] = pd.to_datetime(result["timestamp"]).dt.tz_localize(None).dt.normalize()
    result = result.dropna(subset=["close", "open", "high", "low", "volume"])
    result = result[["symbol", "timestamp", "open", "high", "low", "close", "volume"]]

    if use_cache:
        result.to_parquet(path, index=False)
        _logger.info("data.cache_write path=%s rows=%d", path, len(result))

    return result


def load_sp100_bars(
    start: date,
    end: date,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Load daily bars for the full S&P 100 snapshot universe."""
    return load_bars(SP100, start, end, use_cache=use_cache)
