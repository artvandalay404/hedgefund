"""Point-in-time-safe primitive registry (ADR-0009).

Each primitive has signature f(df, [period]) -> pd.Series.  Rolling
primitives use shift(1) to exclude the current bar, so
`close > rolling_high(20)` compares today's close to the prior-20-bar high —
matching BreakoutStrategy's convention and guaranteeing lookahead safety.

Novel computation enters by registering a new primitive here (human-reviewed),
not by the LLM writing inline code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass
class PrimitiveDef:
    fn: Callable[..., pd.Series]
    has_period: bool
    step: int  # neighbourhood step size (ADR-0010 §3)


def _close(df: pd.DataFrame) -> pd.Series:
    return df["close"].copy()


def _volume(df: pd.DataFrame) -> pd.Series:
    return df["volume"].copy()


def _rolling_high(df: pd.DataFrame, period: int) -> pd.Series:
    return df["high"].shift(1).rolling(period).max()


def _rolling_low(df: pd.DataFrame, period: int) -> pd.Series:
    return df["low"].shift(1).rolling(period).min()


def _sma(df: pd.DataFrame, period: int) -> pd.Series:
    return df["close"].shift(1).rolling(period).mean()


def _ema(df: pd.DataFrame, period: int) -> pd.Series:
    return df["close"].shift(1).ewm(span=period, adjust=False).mean()


def _rsi(df: pd.DataFrame, period: int) -> pd.Series:
    delta = df["close"].shift(1).diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100.0 - 100.0 / (1.0 + rs)


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    h = df["high"].shift(1)
    lo = df["low"].shift(1)
    cp = df["close"].shift(2)
    tr = pd.concat([h - lo, (h - cp).abs(), (lo - cp).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _avg_volume(df: pd.DataFrame, period: int) -> pd.Series:
    return df["volume"].shift(1).rolling(period).mean()


def _k_day_return(df: pd.DataFrame, period: int) -> pd.Series:
    return df["close"].shift(1).pct_change(period)


REGISTRY: dict[str, PrimitiveDef] = {
    "close":        PrimitiveDef(fn=_close,        has_period=False, step=0),
    "volume":       PrimitiveDef(fn=_volume,       has_period=False, step=0),
    "rolling_high": PrimitiveDef(fn=_rolling_high, has_period=True,  step=5),
    "rolling_low":  PrimitiveDef(fn=_rolling_low,  has_period=True,  step=5),
    "sma":          PrimitiveDef(fn=_sma,          has_period=True,  step=5),
    "ema":          PrimitiveDef(fn=_ema,          has_period=True,  step=5),
    "rsi":          PrimitiveDef(fn=_rsi,          has_period=True,  step=2),
    "atr":          PrimitiveDef(fn=_atr,          has_period=True,  step=2),
    "avg_volume":   PrimitiveDef(fn=_avg_volume,   has_period=True,  step=10),
    "k_day_return": PrimitiveDef(fn=_k_day_return, has_period=True,  step=2),
}


def evaluate(df: pd.DataFrame, name: str, period: int | None = None) -> pd.Series:
    """Evaluate a registered primitive against a per-symbol DataFrame."""
    defn = REGISTRY.get(name)
    if defn is None:
        raise ValueError(f"Unknown primitive: {name!r}")
    if defn.has_period:
        if period is None:
            raise ValueError(f"Primitive {name!r} requires a period")
        return defn.fn(df, period)
    return defn.fn(df)
