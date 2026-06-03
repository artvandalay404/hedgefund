"""Compile a StrategySpec into a StrategyBase (ADR-0009).

The LLM authors a spec; this deterministic compiler executes it.
No live LLM call is ever the literal trade trigger (ADR-0002).
"""
from __future__ import annotations

import pandas as pd

from hedgefund.backtest.strategy import StrategyBase, TradeSignal
from hedgefund.quant_research.dsl import PrimitiveSide, StrategySpec
from hedgefund.quant_research.registry import evaluate


class DSLStrategy(StrategyBase):
    def __init__(self, spec: StrategySpec) -> None:
        self.spec = spec

    def signals_for_date(
        self, bars: pd.DataFrame, as_of: pd.Timestamp
    ) -> list[TradeSignal]:
        hist = bars[bars["timestamp"] <= as_of]
        signals = []
        for symbol, grp in hist.groupby("symbol"):
            grp = grp.sort_values("timestamp").reset_index(drop=True)
            if len(grp) < 2:
                continue
            mask = _entry_mask(grp, self.spec)
            if not bool(mask.iloc[-1]):
                continue
            last = grp.iloc[-1]
            entry = float(last["close"])
            stop = _stop_price(grp, len(grp) - 1, entry, self.spec)
            target = entry + self.spec.exit_rule.reward_risk * (entry - stop)
            signals.append(TradeSignal(str(symbol), "long", entry, stop, target))
        return signals

    def precompute(
        self, bars: pd.DataFrame
    ) -> dict[pd.Timestamp, list[TradeSignal]]:
        result: dict[pd.Timestamp, list[TradeSignal]] = {
            day: [] for day in sorted(bars["timestamp"].unique())
        }
        for symbol, grp in bars.groupby("symbol"):
            grp = grp.sort_values("timestamp").reset_index(drop=True)
            if len(grp) < 2:
                continue
            mask = _entry_mask(grp, self.spec)
            for idx in grp[mask].index:
                row = grp.loc[idx]
                day = row["timestamp"]
                if day not in result:
                    continue
                entry = float(row["close"])
                stop = _stop_price(grp, int(idx), entry, self.spec)
                target = entry + self.spec.exit_rule.reward_risk * (entry - stop)
                result[day].append(
                    TradeSignal(str(symbol), "long", entry, stop, target)
                )
        return result


def _eval_side(grp: pd.DataFrame, side: PrimitiveSide | float) -> pd.Series | float:
    if isinstance(side, (int, float)):
        return float(side)
    return evaluate(grp, side.primitive.name, side.primitive.period) * side.scale


def _entry_mask(grp: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    masks: list[pd.Series] = []
    for pred in spec.entry.predicates:
        lhs = _eval_side(grp, pred.lhs)
        rhs = _eval_side(grp, pred.rhs)

        if pred.op == ">":
            m = lhs > rhs
        elif pred.op == "<":
            m = lhs < rhs
        elif pred.op == ">=":
            m = lhs >= rhs
        else:
            m = lhs <= rhs

        if not isinstance(m, pd.Series):
            m = pd.Series(bool(m), index=grp.index)
        masks.append(m.fillna(False))

    if not masks:
        return pd.Series(False, index=grp.index)

    combined = masks[0]
    for m in masks[1:]:
        if spec.entry.logic == "AND":
            combined = combined & m
        else:
            combined = combined | m
    return combined


def _stop_price(
    grp: pd.DataFrame, idx: int, entry: float, spec: StrategySpec
) -> float:
    s = spec.exit_rule.stop
    if s.kind == "percent":
        return entry * (1.0 - s.value)
    atr_series = evaluate(grp, "atr", 14)
    val = atr_series.iloc[idx] if idx < len(atr_series) else float("nan")
    atr_val = float(val) if not pd.isna(val) else entry * 0.02
    return entry - s.value * atr_val


def compile_spec(spec: StrategySpec) -> DSLStrategy:
    """Compile a StrategySpec into a StrategyBase."""
    return DSLStrategy(spec)
