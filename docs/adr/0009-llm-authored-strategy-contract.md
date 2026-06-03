# 9. LLM-authored strategy contract: the authoring boundary

- Status: Accepted
- Date: 2026-06-03
- Deciders: Satwik (Portfolio Manager)
- Extends: [ADR-0002](0002-hybrid-pipeline-architecture.md)

## Context

[#26](https://github.com/artvandalay404/hedgefund/issues/26) asks to make the
quant researcher a first-class *idea generator* — able to turn a theory (PM-given
or self-originated) into a backtestable strategy, run it through the validation
harness, and return results. [ADR-0002](0002-hybrid-pipeline-architecture.md)
fixed the load-bearing rule for the whole system: **LLMs reason; deterministic
code decides and executes; no live LLM call is ever the literal buy/sell
trigger.** An authoring layer has to honour that boundary even though it now lets
an LLM *write the strategy itself*.

Two specific hazards shape the contract:

1. **Arbitrary code is unsafe and unverifiable.** If the LLM emits free-form
   Python, point-in-time safety becomes a *review* problem (nothing structurally
   stops a subtle lookahead, a `datetime.now()`, a network call, or
   non-determinism), and running it unattended needs a sandbox.
2. **Automation is a rate multiplier** ([ADR-0008](0008-validation-data-discipline.md)).
   A loop that authors and tests at machine throughput is exactly what turns
   holdout-mining catastrophic and inflates the multiple-comparisons problem.

This ADR pins the *authoring contract* and its execution boundary. The trial
accounting that makes authoring statistically safe lives in
[ADR-0008](0008-validation-data-discipline.md) and its amendment
[ADR-0010](0010-effective-trial-accounting.md).

## Decision

**1. The LLM emits a constrained spec, not code — an extensible-registry DSL.**
A strategy is a structured, validated spec (pydantic), not Python:

- **Entry** — a boolean AND/OR of comparison predicates over registry primitives
  (optionally scaled by a constant), e.g. `close > rolling_high(20)` AND
  `volume > 1.5 × avg_volume(50)`.
- **Exit** — `stop` ∈ {percent, ATR-multiple}, `target` ∈ {R-multiple}, optional
  `max_hold_days`. (Trailing stops deferred — the engine models a static
  stop/target only.)
- **Per-symbol / time-series only** for v1 — this matches the engine and
  [ADR-0005](0005-trading-scope-universe-strategy-broker-data.md) (long-only,
  per-name bracket orders). Cross-sectional ranking is a different trading model
  (ranked books, rebalance, shorts) tracked separately
  ([#29](https://github.com/artvandalay404/hedgefund/issues/29)).

**2. Primitives are vetted, point-in-time-safe Python functions in a registry.**
Each primitive has the signature `f(history_up_to_t) -> Series` and is only ever
handed past bars, so it is point-in-time-safe **by construction**. The LLM
*composes* primitives; it cannot express "peek ahead" because the vocabulary has
no word for it. Novel computation (e.g. a signal from a paper) enters by
**registering a new primitive under human review** — implemented and tested once,
reused forever — not by the LLM writing inline code. The registry is the growth
path *and* the only unsafe surface, kept tiny and reviewed.

This structurally guarantees the three properties [#26](https://github.com/artvandalay404/hedgefund/issues/26)
demands — **deterministic, parameterized, point-in-time-safe** — with **no
sandbox**.

**3. The authoring boundary (extends ADR-0002).** The LLM authors a *spec*; a
deterministic compiler (`compile_spec → StrategyBase`) and the existing
event-driven executor run it. "Start implementing a strategy" means *generate
spec / scaffold code for review and the gate* — never auto-promote to trading. A
passing LLM-authored strategy still clears the **same rigorous backtest gate**,
the **human promotion** step, and the **forward-paper window** before it counts.
The LLM is never the literal trade trigger.

**4. v1 is human-in-the-loop and rate-limited (operational safety).** The first
build ([#28](https://github.com/artvandalay404/hedgefund/issues/28)) is one
**PM-given** theory per **human-triggered** invocation — no autonomous loop, no
self-generated theories, no auto-PR, and **no holdout touch** (the slice runs
walk-forward only; the holdout stays behind the unchanged human-gated
`evaluate_holdout.py`). This is the operational defence against ADR-0008's *rate*
hazard until the harness's automated effective-trial accounting
([ADR-0010](0010-effective-trial-accounting.md)) is complete. The autonomous
factory remains parked in [#26](https://github.com/artvandalay404/hedgefund/issues/26),
gated on a real track record ([ADR-0007](0007-build-sequencing-and-roadmap.md)).

**5. Hindsight priors get an advisory rationale, not an automated gate.** The
LLM's training already encodes which historical anomalies paid off, contaminating
the *hypothesis space* (distinct from holdout violation — it touches no data, and
return-space effective-N does **not** catch it). Every spec must carry a
**four-part economic rationale**: (a) the mechanism, (b) why it hasn't been
arbitraged away, (c) what would break it, (d) disclosure of any known published
anomaly it maps to (+ citation). It is logged and surfaced for **human review**
with **no automated effect** — gating on credibility would only train the model
to write plausible-sounding prose (Goodhart). The genuine antidote is
forward-paper, which the model cannot pattern-match to; that gate is out of the
v1 slice's scope and documented as such.

## Consequences

- The validation harness is generalized off `BreakoutStrategy` to consume
  `(config_identity, StrategyBase)` pairs, preserving the DSR/PBO/trial-logging
  machinery (the breakout's params dict becomes its identity).
- A new `hedgefund/quant_research/` package (`dsl.py`, `compiler.py`,
  `neighborhood.py`, `author.py`) plus `scripts/author_strategy.py`.
- This introduces the **first LLM call in the system**, *ahead of* the
  qualitative branch's runtime LLM. Acceptable: authoring is **offline and
  human-gated**, never in the trade loop, so it does not violate ADR-0002's
  execution boundary or pre-empt the Phase-3 runtime LLM.
- A known ceiling: per-symbol-only authoring cannot express the cross-sectional
  factor literature ([#29](https://github.com/artvandalay404/hedgefund/issues/29)).

## Alternatives considered

- **Free-form Python + sandbox + an empirical lookahead test** (mask future bars,
  assert outputs don't shift). Maximally expressive, but the lookahead guarantee
  is *probabilistic* over untestable paths, it needs a sandbox, and every strategy
  re-implements (and re-bugs) its own indicators. Rejected: a paper-first,
  rails-before-capital system prefers **structural** safety to probabilistic.
- **Archetype + parameters** (LLM picks a hand-written template, sets params).
  Safest, but barely more than the existing `PARAM_GRID` — it does not actually
  *author* a strategy. Rejected as too weak to be the idea-generation layer.
