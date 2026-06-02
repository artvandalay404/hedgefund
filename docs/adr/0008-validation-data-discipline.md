# 8. Validation-data discipline: trial accounting and data-tier gating

- Status: Accepted
- Date: 2026-06-02
- Deciders: Satwik (Portfolio Manager)
- Extends: [ADR-0003](0003-two-branch-alpha-and-validation-asymmetry.md)

## Context

[ADR-0003](0003-two-branch-alpha-and-validation-asymmetry.md) established the
**rigorous backtest** gate (walk-forward, untouched holdout, point-in-time data,
modeled slippage/spread, survivorship-bias-free membership) but did not say how
the holdout stays trustworthy across *repeated* research. That gap becomes
load-bearing once the quant researcher can author and test strategies at machine
throughput (#26).

Two facts force the issue:

1. **A holdout is a one-time instrument.** Its validity rests on never being
   *conditioned on*. Every time a result is read and then used to change the
   strategy, a degree of freedom is spent; selection bias inflates the best
   observed Sharpe by roughly `σ·√(2·ln N)` over `N` trials. The damage is
   indifferent to whether a candidate is a parameter tweak or a brand-new
   strategy — trials are lottery tickets, not novelty.

2. **Automation is the multiplier.** A human hands over a handful of theories a
   month; an automated loop can test thousands. Automation collapses the cost of
   the test–select–refine cycle, which is precisely what turns holdout-mining
   from manageable into catastrophic. (A second, LLM-specific hazard:
   hindsight-contaminated priors — the model already "knows" what worked
   historically — contaminate the *hypothesis space* itself, distinct from
   holdout violation. See #26.)

The danger is therefore not *who or what generates an idea* — generation touches
no data — but *closing a refinement loop over the holdout, at scale*.

## Decision

**1. Three data tiers; a strategy progresses through them in order.**

- **In-sample + walk-forward — unlimited iteration.** Combinatorial Purged
  Cross-Validation with **purge + embargo** around each test fold to stop leakage
  from overlapping label windows. All development happens here.
- **Sealed archived holdout — one shot, human-gated.** A *frozen* strategy (all
  parameters fixed) is run against the untouched holdout exactly once. The touch
  is an explicit human-approved operation an automated loop cannot reach.
- **Forward paper — the only genuinely-fresh out-of-sample.** A promoted strategy
  must survive a forward paper window before its results count toward the
  **official track record**. The archived holdout is correlated with in-sample by
  shared regime and universe; the future is the only uncorrelated test.

Two truly-independent out-of-sample gates (archived holdout + forward paper) beat
three correlated slices of one archive. **You cannot iterate faster than time
passes.**

**2. Two trial counters ("N"), tracked separately.**

- **search-N** — every configuration evaluated against in-sample/walk-forward.
  Large; deflates the *in-sample* metric used to choose which candidates advance.
- **holdout-N** — distinct frozen strategies evaluated against a given holdout.
  Must stay ≈1. **Modify-then-retest against the holdout is the forbidden move.**

A single frozen strategy touching the holdout once needs **no** deflation — the
holdout independently catches in-sample overfitting (an overfit strategy
*underperforms* out-of-sample). Deflation by trial count applies to (a) the
in-sample metric, by search-N, and (b) the holdout metric, only if holdout-N > 1.

**3. The pass bar scales with trials.** Significance is the **Deflated Sharpe
Ratio** (P(true Sharpe > 0) given trial count, cross-trial dispersion, sample
length, skew, kurtosis) plus **Probability of Backtest Overfitting (PBO)** — never
a raw Sharpe versus zero. Every evaluated configuration logs its return series and
Sharpe, not just the winner; N is honest only if every config that *could have
been selected* is counted. (Formulae and the two sigmas live in the harness
spec, #16.)

**4. N is a property of a data partition, not of a strategy or a session.** It is
a **monotonic per-partition counter that never decrements.** A new strategy does
not reset search-N — the data remembers every attempt against it. A holdout
period's N is **cumulative across all research ever run on it**; once touched it
never resets, so well-trodden periods are treated as heavily deflated. The only
genuine reset to N≈0 is fresh, never-queried data — i.e., the future. Forward
paper mints N≈0 data at one day per day; the official track record is just
accumulating forward-N. Strategies record which partitions they touched and at
what counter value, so a strategy may carry a huge in-sample-N but a clean
forward-N.

**5. Self-generation is permitted and safe under this contract.** Because
generation does not touch data, a self-originated theory and a PM-given theory
are symmetric with respect to holdout integrity. The defense is this contract and
the human-gated holdout — **not** a ban on the quant researcher generating its own
ideas (#26).

## Consequences

- The throughput of *validated* strategies is bounded by wall-clock time, because
  forward paper is the only clean out-of-sample and it accrues one day per day.
  The in-sample search can run as hot as we like; trust accrues slowly.
- Requires persistence for per-partition trial counters and per-trial logging
  (return series + Sharpe), and an explicit human-gated holdout-evaluation step.
- LLM self-authoring (#26) becomes safe to build *on top of* the harness; it must
  not ship before the harness implements this contract (#16).
- A strategy can be honestly described as "heavily searched in-sample, clean on
  forward data" — the attribution stays interpretable.

## Alternatives considered

- **Refresh the holdout every test / require k passes on k rotated holdouts.** The
  instinct (more independent out-of-sample confirmation) is right, but archive
  slices are correlated (shared regime/universe), so passing several is far weaker
  than it looks; rotation only helps with genuinely new hypotheses, not
  refinements of one lineage (the union of rotated holdouts becomes in-sample for
  that lineage); and the multiple-comparisons leak simply moves up to the
  battery level. A strict k-of-k AND also rejects real edges that miss one
  regime. Rejected in favor of tiering + deflation + a genuinely-forward gate.
- **Ban the quant researcher from generating its own theories.** Misdiagnoses the
  risk — generation never touches the holdout; the hazard is rate, addressed by
  the contract above. Rejected; it would also waste a real alpha source.
- **Keep raw Sharpe versus zero as the bar.** Ignores trial count and guarantees
  false positives under automated search. Rejected for the Deflated Sharpe Ratio
  + PBO.
