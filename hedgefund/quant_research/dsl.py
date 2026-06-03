"""DSL spec for LLM-authored strategies (ADR-0009).

The LLM emits a StrategySpec — a structured, pydantic-validated spec over
registry primitives. It never emits Python. The compiler turns the spec into
a StrategyBase executable by the existing backtester.
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


VALID_PRIMITIVES = frozenset({
    "close", "volume", "rolling_high", "rolling_low",
    "sma", "ema", "rsi", "atr", "avg_volume", "k_day_return",
})


class PrimitiveRef(BaseModel):
    name: str
    period: int | None = None

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if self.name not in VALID_PRIMITIVES:
            raise ValueError(
                f"Unknown primitive {self.name!r}. Valid: {sorted(VALID_PRIMITIVES)}"
            )


class PrimitiveSide(BaseModel):
    """A registry primitive, optionally scaled: primitive * scale."""
    primitive: PrimitiveRef
    scale: float = 1.0


class Predicate(BaseModel):
    """One comparison in the entry condition: lhs op rhs."""
    lhs: PrimitiveSide
    op: Literal[">", "<", ">=", "<="]
    rhs: PrimitiveSide | float  # scaled primitive or numeric literal


class EntryCondition(BaseModel):
    logic: Literal["AND", "OR"] = "AND"
    predicates: list[Predicate]


class StopSpec(BaseModel):
    kind: Literal["percent", "atr_multiple"]
    value: float  # 0.02 = 2% stop, or 2.0 = 2× ATR


class ExitSpec(BaseModel):
    stop: StopSpec
    reward_risk: float = 2.0   # R-multiple for target
    max_hold_days: int | None = None  # reserved; engine uses stop/target only


class EconomicRationale(BaseModel):
    mechanism: str
    why_not_arbitraged: str
    what_would_break_it: str
    known_anomaly_disclosure: str   # cite known anomaly or "None known"


class StrategySpec(BaseModel):
    """Complete, compiler-ready strategy spec emitted by the LLM author."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    direction: Literal["long"] = "long"
    entry: EntryCondition
    exit_rule: ExitSpec = Field(alias="exit")
    rationale: EconomicRationale

    def config_identity(self) -> dict:
        """Stable keying dict (excludes advisory rationale) for harness + trial log."""
        return json.loads(
            self.model_dump_json(
                include={"name", "direction", "entry", "exit_rule"},
                by_alias=True,
            )
        )
