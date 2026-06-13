# 10. Effective-trial accounting: deflate by independence, not raw count

- Status: Accepted
- Date: 2026-06-03
- Deciders: Satwik (Portfolio Manager)
- Amends: [ADR-0008](0008-validation-data-discipline.md)

## Context

[ADR-0008](0008-validation-data-discipline.md) §1 deliberately chose a
*conservative* simplification: count every configuration as a full trial,
"indifferent to whether a candidate is a parameter tweak or a brand-new
strategy — trials are lottery tickets, not novelty." Over-counting is safe, so
this was the right call when the only thing touching the data was a single
hand-built strategy.

Two developments make raw counting actively wrong:

1. **The neighbor family.** [ADR-0009](0009-llm-authored-strategy-contract.md) /
   [#28](https://github.com/artvandalay404/hedgefund/issues/28) evaluate a small,
   deliberately-tight robustness neighborhood around each canonical spec so that
   PBO is computable. By construction those K configs are ~95% correlated — they
   are *one bet, not K bets*. Charging the partition K trials **over-deflates**
   and punishes the system for doing a robustness check.
2. **The autonomous factory.** [#26](https://github.com/artvandalay404/hedgefund/issues/26)
   will generate many strategies, many of them near-duplicates. The honest
   multiple-comparisons quantity is the **effective number of *independent*
   trials**, not the headcount.

The selection-bias inflation ADR-0008 §1 cites (`σ·√(2·ln N)`) is a result for
**independent** trials; correlated trials inflate the observed max far less. The
correct `N` is therefore the *effective* number of independent trials.

## Decision

**1. Deflate by effective-N, measured in return space — not by raw count, not in
parameter space.** A strategy *is* its out-of-sample return series (a vector over
trading days). Two strategies are "the same trial" to the extent their PnL is
correlated. Parameter-space distance is rejected: knobs are not comparable across
strategy families, and raw param distance does not track behavioural similarity.

**2. Marginal trial cost = the orthogonal residual (1 − R²).** When a new
strategy is evaluated, regress its return vector on the span of the
already-tested population's return vectors; charge the partition the fraction of
its variance that is **orthogonal** to everything before it (1 − R²). A strategy
reconstructible from prior trials adds ≈ 0; a genuinely novel return stream adds
≈ 1. This is monotonic (only ever adds a non-negative residual, preserving
ADR-0008 §4's "never decrements"), has **no gameable global denominator**, is
immune to dense-path "death by a thousand cuts" mining (collinear steps span one
direction → add ~1 jointly), and catches a *relabeled* known strategy that a
"new family → +1" rule would miss.

**3. Minimal scope now ([#28](https://github.com/artvandalay404/hedgefund/issues/28)).**
Charge the harness-generated neighbor family as **~1 effective trial** via the
**participation ratio** of its K×K return-correlation matrix
(`N_eff = (Σλ)² / Σλ²` over the correlation eigenvalues). This requires
persisting each trial's return series (`trial_log.returns_json`, currently `[]`).

> **Amended 2026-06-06.** The participation ratio is no longer the *charge*; it
> is a reported diagnostic. One **authoring run** — the canonical spec, its
> ±1-step neighbour variants, and every walk-forward fold — charges the
> partition a flat **1**, incremented once per run in `pipeline.run_authoring`.
> Neighbours are a robustness check and folds are CV slices of a single
> evaluation: *one bet, not N*. The participation ratio is retained as a
> **guardrail** (an eff-N materially above 1 means the neighbourhood isn't
> tight) and stays the candidate charge mechanism for #26's heterogeneous
> populations, where a flat 1 would be gameable. Return-series persistence
> (`trial_log.returns_json`) still stands, for that diagnostic and for #26.
> **Scope note:** this covers the DSL authoring pipeline's robustness
> neighbourhood only. A deliberate **parameter grid search** that *selects* a
> best config (e.g. `scripts/run_backtest.py`'s `PARAM_GRID`) is genuine
> multiple comparisons and is **not** collapsed to 1 — see §Consequences.

**4. Full scope parked ([#26](https://github.com/artvandalay404/hedgefund/issues/26)).**
Population-wide 1 − R² accrual plus a **saturation guard**: as the number of
tested strategies approaches the number of trading days `T`, any vector becomes
linearly reconstructible (R² → 1 spuriously) and N_eff would stop growing exactly
when mining is hottest. The guard (cap/shrink the regression basis, or cluster
trials) must ensure **N_eff cannot saturate**.

**5. Unchanged from ADR-0008.** Search-N remains a **monotonic, data-keyed**
per-partition counter — and the implementation is corrected to key on *data
identity only* (`sp100_is_2015_2022`, migrating the old
`sp100_breakout_is_*` count) so every strategy ever tested against a panel shares
one counter, per ADR-0008 §4. Holdout-N ≈ 1 stays human-gated; forward-paper
remains the only genuinely-fresh out-of-sample.

## Consequences

- Search-N becomes **fractional**; the DSR deflation consumes effective-N.
  **Amended 2026-06-06:** under §3-amended each authoring run charges a flat
  **1**, so per-partition search-N stays an **integer** counter and the
  participation ratio is diagnostic, not consumed. (#26's population-wide 1−R²
  accrual may reintroduce fractional charges.) `scripts/run_backtest.py`'s grid
  search charges **one increment per distinct config** (not per fold-result).
  And the in-sample DSR deflation in `WalkForwardResult.summary()` now consumes
  that **search-N** (ADR-0008 §2), replacing an ad-hoc `len(folds)` count, while
  the **holdout** DSR deflates by **holdout_n** (fixing a `search_n` value that
  had been mis-passed as the return-series length). Both bring the code into
  line with ADR-0008's existing contract — see ADR-0008 §2/§4.
- `trial_log` must store per-trial return series (it has the `returns_json`
  column; runners must stop passing `[]`).
- Effective-N is an **in-sample, linear** estimate — strategies orthogonal
  in-sample may correlate out-of-sample, and non-linear relationships read as
  orthogonal. It is a sharper approximation than raw count, not a law; this is
  why forward-paper, not cleverer in-sample accounting, remains the real gate.

## Alternatives considered

- **Keep raw trial counting (ADR-0008 §1 as written).** Simple and safe, but
  over-deflates correlated trials and penalizes robustness checks. Superseded.
- **Parameter-space distance, normalized by the farthest pair** (the first
  proposal). Rejected: the global max-distance denominator is gameable (add two
  outliers → everything else looks cheap), and a moving farthest-pair would
  *retroactively shrink* prior contributions, breaking ADR-0008 §4's monotonicity.
- **Discrete "new family → +1, neighbor → fraction" rule.** Rejected: "family" is
  an undefined, gameable boundary; the continuous orthogonality measure makes the
  family distinction *emergent* and unspoofable.
