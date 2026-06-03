"""LLM strategy authoring: PM theory → StrategySpec (ADR-0009).

Uses Anthropic Messages API with tool-use forcing to emit a validated
StrategySpec.  The system prompt is prompt-cached (cache_control: ephemeral)
since it is large and reused across all authoring calls.

Model: claude-opus-4-8 (quality matters; authoring is low-frequency and
       offline — never in the trade loop).
"""
from __future__ import annotations

import textwrap

import anthropic
from pydantic import ValidationError

from hedgefund.config import settings
from hedgefund.quant_research.dsl import StrategySpec

AUTHOR_MODEL = "claude-opus-4-8"
MAX_TOKENS = 4096
MAX_REPAIR_ATTEMPTS = 1

_SYSTEM = textwrap.dedent("""\
    You are a quantitative strategy author for a systematic trading system.
    Your task: turn a natural-language trading theory into a precise,
    machine-executable strategy spec by calling the emit_strategy_spec tool.

    ═══ Primitive registry ════════════════════════════════════════════════════

    These are the ONLY building blocks you may use.  Each returns a
    per-bar time-series value, computed using only data strictly before the
    current bar (point-in-time safe — no lookahead by construction).

    | Name          | Period? | Description                                 |
    |---------------|---------|---------------------------------------------|
    | close         | No      | Current bar's closing price                 |
    | volume        | No      | Current bar's volume                        |
    | rolling_high  | Yes (≥2)| Max of prior N bars' highs                  |
    | rolling_low   | Yes (≥2)| Min of prior N bars' lows                   |
    | sma           | Yes (≥2)| Simple moving avg of prior N closes         |
    | ema           | Yes (≥2)| Exponential moving avg of prior N closes    |
    | rsi           | Yes (≥2)| RSI over prior N periods (0–100)            |
    | atr           | Yes (≥2)| Average True Range over prior N periods     |
    | avg_volume    | Yes (≥2)| Mean of prior N bars' volumes               |
    | k_day_return  | Yes (≥2)| N-day price return (prior bars, decimal)    |

    ═══ DSL grammar ═══════════════════════════════════════════════════════════

    Entry condition: AND or OR of comparison predicates.
    Each predicate:  LHS op RHS
      LHS: a PrimitiveSide  (primitive reference, optionally scaled)
      op:  one of  >  <  >=  <=
      RHS: a PrimitiveSide OR a numeric literal

    PrimitiveSide JSON:  {"primitive": {"name": "...", "period": N}, "scale": 1.0}
      - "period" is omitted (null) for no-period primitives (close, volume)
      - "scale" multiplies the primitive value (default 1.0)

    Numeric literal RHS: just a JSON number, e.g.  30.0

    Exit spec:
      stop.kind:    "percent"     → stop = entry * (1 − value),   e.g. value=0.02
                    "atr_multiple"→ stop = entry − value * ATR(14), e.g. value=2.0
      reward_risk:  target = entry + reward_risk * (entry − stop)
      max_hold_days (optional, reserved — engine uses stop/target only)

    ═══ Example specs ═════════════════════════════════════════════════════════

    1. Volume-confirmed breakout (v1 canonical):
       entry: close > rolling_high(20) AND volume > avg_volume(50) * 1.5
       exit:  stop=percent(0.02), reward_risk=2.0

       JSON entry predicates:
       [
         { "lhs": {"primitive": {"name": "close"}, "scale": 1.0},
           "op": ">",
           "rhs": {"primitive": {"name": "rolling_high", "period": 20}, "scale": 1.0} },
         { "lhs": {"primitive": {"name": "volume"}, "scale": 1.0},
           "op": ">",
           "rhs": {"primitive": {"name": "avg_volume", "period": 50}, "scale": 1.5} }
       ]

    2. RSI oversold bounce:
       entry: rsi(14) < 30.0
       exit:  stop=percent(0.03), reward_risk=2.0

       JSON entry predicates:
       [
         { "lhs": {"primitive": {"name": "rsi", "period": 14}, "scale": 1.0},
           "op": "<",
           "rhs": 30.0 }
       ]

    ═══ Economic rationale (required) ════════════════════════════════════════

    Every spec must include a four-part rationale for human review:
      mechanism:              Causal mechanism — why should this generate alpha?
      why_not_arbitraged:     Why hasn't competition fully eliminated this edge?
      what_would_break_it:    What regime change or structural shift would kill it?
      known_anomaly_disclosure: Name any known published anomaly this maps to
                               (with citation), or state "None known" if novel.
                               Be honest — this is logged for human review.

    ═══ Output rules ══════════════════════════════════════════════════════════

    - Call emit_strategy_spec exactly once.
    - name: short snake_case, e.g. "rsi_oversold_bounce"
    - direction: always "long" (v1 is long-only)
    - All numeric values must be positive.
    - period integers must be ≥ 2.
    - scale values must be positive floats.
    - Do NOT invent primitive names outside the registry above.
""")

_TOOL: dict = {
    "name": "emit_strategy_spec",
    "description": (
        "Emit one complete, validated strategy spec in the DSL. "
        "Call this tool exactly once after reading the theory."
    ),
    "input_schema": StrategySpec.model_json_schema(by_alias=True),
}


def author_strategy(theory: str) -> StrategySpec:
    """Author a StrategySpec from a PM-given theory string.

    Makes one Anthropic API call with up to one repair retry on validation
    failure.  Returns a validated StrategySpec; raises on unrecoverable error.
    """
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages: list[dict] = [
        {
            "role": "user",
            "content": f"Theory: {theory}\n\nPlease emit a strategy spec.",
        }
    ]

    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        response = client.messages.create(
            model=AUTHOR_MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[_TOOL],
            tool_choice={"type": "any"},
            messages=messages,
        )

        for block in response.content:
            if block.type != "tool_use" or block.name != "emit_strategy_spec":
                continue

            try:
                return StrategySpec.model_validate(block.input)
            except ValidationError as exc:
                if attempt >= MAX_REPAIR_ATTEMPTS:
                    raise

                # Feed error back: assistant tool-use → user tool-result → retry
                messages.append({
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                    ],
                })
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": (
                                f"Validation failed:\n{exc}\n\n"
                                "Fix the errors and call emit_strategy_spec again."
                            ),
                            "is_error": True,
                        }
                    ],
                })
                break

    raise RuntimeError(
        "LLM did not emit a valid strategy spec after repair attempt."
    )
