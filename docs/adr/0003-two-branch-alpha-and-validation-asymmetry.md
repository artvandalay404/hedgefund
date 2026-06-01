# 3. Two-branch alpha model and its validation asymmetry

- Status: Accepted
- Date: 2026-06-01
- Deciders: Satwik (Portfolio Manager)

## Context

We want the best ideas to surface whether they come from a quantitative angle
(price/volume/indicators with a good backtest) or a qualitative angle (an LLM
reasoning about catalysts and price reactions). This mirrors how multi-strategy
funds combine a systematic sleeve and a discretionary sleeve.

A trap hides in the qualitative idea. When an LLM "goes back in time" to study
what news drove a past move, **it already knows how the story ended** — those
events are in its training data — and its judgment cannot be replayed bar-by-bar.
So the qualitative branch **cannot be honestly backtested** the way a systematic
strategy can.

## Decision

Run **two parallel alpha branches, each able to *originate* a trade**:

- **Quant branch** — systematic strategies; **must clear the rigorous backtest**
  (walk-forward, untouched holdout, point-in-time data, modeled slippage/spread,
  survivorship-bias-free membership) before trading.
- **Qualitative branch** — an LLM that studies catalysts (earnings surprises,
  guidance, analyst revisions, news) and emits forward-looking theses.

**Validation is asymmetric — deliberately:**

- Quant: backtested as above.
- Qualitative: **forward-validated only.** It earns trust by its live paper
  record, starts at small size, and scales up only if it demonstrably adds value
  going forward. No backtest of its judgment is treated as evidence.

**Attribution makes this honest.** Every trade is tagged into one of three
**attribution buckets** — `quant-solo`, `qual-solo`, `consensus` — so each
branch's standalone contribution is measurable, and we can see whether consensus
beats quant-solo.

**Branches collaborate on sizing, not on the execution trigger.** Each branch
proposes independently; the deterministic risk model sets a **base size**; an
**agreement multiplier** adjusts it (see [ADR-0004](0004-risk-management-framework.md)).
Code still executes; a branch can only *propose* or, on conflict, *veto*.

The deterministic risk caps and the kill switch **bind both branches**
unconditionally.

## Consequences

- We get a real discretionary alpha source without pretending it's been proven.
- We will *know* whether the LLM sleeve is any good, from the bucketed P&L.
- The qualitative branch needs a **structured, evidence-cited output contract**
  (name, direction, entry/stop/target, horizon, cited catalyst, calibrated
  conviction) so it stays disciplined rather than vibey. (Spec to be written.)
- "Going back in time" remains useful for **hypothesis generation** but is never
  evidence of edge.

## Alternatives considered

- **Qualitative as veto-only** — Safer, but wastes a genuine alpha source and
  contradicts the goal of letting the best ideas surface. Rejected.
- **Point-in-time sandbox to "fix" backtesting the LLM** — The model's parametric
  memory still leaks; mitigation, not a cure. Not relied upon.
- **Qualitative as hypothesis-generator only** (must become backtestable rules) —
  Keeps one integrity standard but loses real-time discretionary alpha. Rejected
  for v1; remains the path for the future quant strategy-factory.
- **Conviction-score blend / independent sleeves** for sizing — Blend blurs
  attribution; pure independence isn't real collaboration. Rejected in favor of
  base × agreement multiplier ([ADR-0004](0004-risk-management-framework.md)).
