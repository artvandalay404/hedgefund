# Build plan

Three phases, per [ADR-0007](adr/0007-build-sequencing-and-roadmap.md). This file
is the human-readable plan; [`scripts/create-github-issues.sh`](../scripts/create-github-issues.sh)
creates the matching GitHub issues and labels.

## Phase 1 — Walking skeleton

**Goal:** thinnest end-to-end loop trading paper unattended and emailing you.
**Proves plumbing; results do NOT count as track record.**

**Exit criteria:** on a schedule, the system reads the universe, places and
manages at least one paper bracket order via the broker interface, persists all
state to Postgres, and sends both a pre-market and a post-market email — running
on the managed host, not a laptop.

1. Project scaffolding & config — Python project, dependencies, env/secrets
   handling, structured logging, test harness.
2. Broker interface + Alpaca paper adapter — account, positions, fills, and
   bracket/OCO order placement behind a swappable interface ([ADR-0005]).
3. Market data layer — S&P 100 universe list + daily price/volume bars (Alpaca).
4. Postgres state schema & data access — positions, orders, **trades tagged by
   branch**, signals, theses, equity_curve, run logs.
5. Risk & sizing module — fixed-fractional sizing, conservative caps, portfolio
   heat, kill switch, agreement multiplier ([ADR-0004]).
6. Orchestrated pre-/post-market pipeline — scheduler entrypoints and cycle steps
   ([ADR-0002]).
7. Email reporting — transactional email + pre-/post-market templates ([ADR-0006]).
8. Deploy to managed host + cron + Postgres — secrets, schedule, healthcheck.
9. End-to-end smoke test — token paper trade + both emails (Phase 1 exit).

## Phase 2 — Quant edge gate

**Goal:** validate the volume-confirmed breakout rigorously.
**Passing the gate opens the official paper track record.**

**Exit criteria:** the breakout strategy clears walk-forward + untouched-holdout
validation with modeled costs and survivorship-bias-free membership, and is
promoted into the live pipeline with quant-solo attribution reporting.

10. Event-driven backtester — point-in-time data, slippage/spread, honest
    intraday stop/target modeling ([ADR-0003]).
11. Survivorship-bias-free S&P 100 historical membership — acquire or document
    the limitation. *(decision/spend — human)*
12. Volume-confirmed breakout strategy — signal spec + parameters ([ADR-0005]).
13. Rigorous validation harness — walk-forward, untouched holdout, metrics,
    overfit/robustness checks.
14. Promote validated quant branch to live; begin official paper track record.
15. Quant-solo attribution + reporting integration.

## Phase 3 — Qualitative branch

**Goal:** add the forward-validated discretionary LLM sleeve.

**Exit criteria:** the qualitative branch emits structured, evidence-cited theses
that flow through agreement-multiplier sizing, with three-bucket attribution
visible in the digests and a defined scaling policy.

16. Catalyst data ingestion — earnings dates/surprises, guidance, analyst
    revisions, news.
17. **Define** qualitative branch structured output contract — name, direction,
    entry/stop/target, horizon, cited catalyst, calibrated conviction. *(decision — human)*
18. Qualitative thesis engine — LLM stage producing theses per the contract
    ([ADR-0003]).
19. Branch arbitration & agreement-multiplier sizing integration ([ADR-0004]).
20. Three-bucket forward attribution + qual scaling policy.
21. Reporting — theses, consensus trades, per-branch attribution in digests.

## Open decisions (not yet scheduled)

- **Phase-2/3 expansion triggers** — what track-record threshold (Sharpe, months
  profitable, max-drawdown survived) unlocks more capital, a wider universe, the
  strategy-factory, and new asset classes. *(decision — human)*

[ADR-0002]: adr/0002-hybrid-pipeline-architecture.md
[ADR-0003]: adr/0003-two-branch-alpha-and-validation-asymmetry.md
[ADR-0004]: adr/0004-risk-management-framework.md
[ADR-0005]: adr/0005-trading-scope-universe-strategy-broker-data.md
[ADR-0006]: adr/0006-stack-runtime-and-reporting.md
