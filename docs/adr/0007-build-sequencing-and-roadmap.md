# 7. Build sequencing and phase roadmap

- Status: Accepted
- Date: 2026-06-01
- Deciders: Satwik (Portfolio Manager)

## Context

v1 carries two distinct risks: **integration risk** (broker, deploy, email,
Postgres all working unattended) and **edge-validation risk** (does the breakout
actually work?), plus the harder qualitative branch on top. As a solo build, the
order of attack determines whether the loop ever closes.

A principle from [ADR-0003](0003-two-branch-alpha-and-validation-asymmetry.md):
paper trading that *counts* must be earned by passing the rigorous backtest. But
proving the **plumbing** need not wait for a proven **edge**.

## Decision

Build in three phases. Separate "proving the plumbing" from "the track record
that counts."

**Phase 1 — Walking skeleton (plumbing; NOT track record).**
Thinnest end-to-end loop: broker interface + Alpaca paper adapter, data layer,
Postgres state, the deterministic risk/sizing module, the orchestrated pre-/post-
market pipeline, and email. Wire in the breakout signal, but treat any trading as
a connectivity/plumbing test — **explicitly not** a track record. Watch it trade
paper and email you within a week or two. Retires integration risk early.

**Phase 2 — Quant edge gate (opens the official track record).**
Build the event-driven backtester (point-in-time, costs, honest stop modeling),
acquire/handle survivorship-bias-free membership, implement the volume-confirmed
breakout, and run rigorous walk-forward + holdout validation. **Passing the gate
opens the official paper track record.**

**Phase 3 — Qualitative branch (forward-validated).**
Build the catalyst data ingestion and the LLM thesis engine (structured,
evidence-cited output contract), integrate the agreement-multiplier sizing, and
stand up the three-bucket forward attribution. Runs alongside the quant branch at
small size, scaling only on demonstrated forward value.

## Roadmap beyond v1 (parked, gated on a real track record)

- **Widen the universe** down the cap spectrum; add more quant strategies.
- **LLM strategy-factory** — auto-generate/backtest quant strategies, under the
  same rigorous out-of-sample gate.
- **New asset classes** — options, then **prediction markets** (a wholly separate
  venue/integration regardless of broker). Unlocked by capital/track-record
  thresholds **to be defined**.
- **Going live** on real capital — reopens the human-approval/oversight model
  ([ADR-0001](0001-paper-first-trading-posture.md)).
- **Web dashboard** and **social-media sentiment**.

## Consequences

- Integration risk is retired first; you see a running system early.
- The "paper must be earned" rule is preserved for what *counts*.
- **Open item:** the Phase-2/3 capital and asset-class expansion **triggers**
  (e.g., Sharpe, months profitable, max-drawdown survived) are not yet defined.
- **Open item:** the qualitative branch's structured output contract needs a spec
  before Phase 3.

## Alternatives considered

- **Quant edge first, then build the loop** — Most disciplined about never
  running an unproven edge, but leaves integration risk un-retired with nothing
  running for weeks. Rejected.
- **Foundations + both branches in parallel** — Fastest to the full vision, but
  the most to juggle solo and the easiest to leave half-finished. Rejected.
