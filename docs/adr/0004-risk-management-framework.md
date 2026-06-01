# 4. Risk management framework

- Status: Accepted
- Date: 2026-06-01
- Deciders: Satwik (Portfolio Manager)

## Context

The system trades autonomously (in paper). Autonomy without hard, code-enforced
guardrails is just an unsupervised way to lose money — and the same controls
must protect us if/when we go live. Risk is deterministic code that both alpha
branches plug into ([ADR-0003](0003-two-branch-alpha-and-validation-asymmetry.md)).

## Decision

**Sizing: fixed-fractional risk per trade.** Each trade risks the same fixed
fraction of equity; share count is derived from the distance to the stop (wider
stop → smaller position). This couples cleanly to the broker-side bracket stops.

**Conservative v1 limits preset:**

| Limit                      | Value                                              |
| -------------------------- | -------------------------------------------------- |
| Risk per trade             | 0.5% of equity                                     |
| Max concurrent positions   | 8                                                  |
| Max notional per name       | 15% of equity                                      |
| Max portfolio heat          | 4% (sum of open per-trade risk)                    |
| Kill switch — drawdown      | Halt new entries at −10% from equity peak          |
| Kill switch — daily loss    | Pause the day at −3% daily loss                    |

**Branch-collaboration sizing: base size × agreement multiplier.** The risk
model sets a **base size** from fixed-fractional risk; then:

- **Solo** proposal (one branch) → ~1× base, tagged to that branch.
- **Consensus** (both branches agree on name/direction) → scale up ~1.5×,
  **subject to all caps above**, tagged `consensus`.
- **Conflict** (branches disagree) → cut hard or **veto to zero**.

All caps and the kill switch are the **final authority** and bind regardless of
branch or conviction.

## Consequences

- A single trade — or a bug — can do only bounded damage while the edge is
  unproven.
- Drawdowns stay shallow; there is ample room to *observe* system behavior.
- Sizing yields the three clean attribution buckets needed by
  [ADR-0003](0003-two-branch-alpha-and-validation-asymmetry.md).
- The preset is intended to be **loosened deliberately** (toward a "Moderate"
  posture: ~1%/trade, 10 positions, 7% heat) only after months of clean results.

## Alternatives considered

- **Equal-weight / fixed allocation** — Ignores stop distance, so risk per trade
  swings with volatility. Less principled. Rejected.
- **Volatility-targeted (ATR) sizing** — More sophisticated but more parameters
  than v1 needs before the edge is proven. Deferred.
- **Moderate / Aggressive limit presets** — Faster compounding, deeper drawdowns;
  unjustified while the edge is unproven. Deferred.
