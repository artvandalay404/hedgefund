# 5. Trading scope: universe, first strategy, broker, and data

- Status: Accepted
- Date: 2026-06-01
- Deciders: Satwik (Portfolio Manager)

## Context

v1 needs a concrete, narrow scope: what we trade, how we enter, where we route
orders, and what data feeds the decision. The goal of v1 is to **prove the
pipeline end-to-end**, not to maximize returns — so cleanliness beats edge.

## Decision

**Universe: the S&P 100.** ~100 mega-caps: trivial to scan, effectively zero
slippage, clean data. Honest trade-off: mega-caps are the most efficient names,
so the breakout edge is *weakest* here — acceptable for proving rails. Widen down
the cap spectrum later.

**First quant strategy: volume-confirmed breakout.** Enter on a new N-day high
with volume well above its trailing average (e.g., > ~1.5× the 50-day average);
stop just below the breakout level; exit on a target or trailing stop. Uses only
price+volume (free data), holds days-to-weeks (true swing), and is cleanly
backtestable. Volume is a **first-class signal**, not a filter.

**Broker: Alpaca, behind a swappable broker interface.** Alpaca offers free,
first-class paper trading, a clean API, native bracket/OCO orders, and stocks +
options under one API. We wrap it behind a thin **broker-agnostic interface** so
adding Interactive Brokers or a prediction-market venue later is a new adapter,
not a rewrite.

**Execution: broker-side bracket orders.** Entry, stop, and target submitted
together; the broker enforces the stop/target intraday. At S&P 100 scale we are
price-takers, so active liquidity management is unnecessary in v1.

**Data scope: price+volume + news + fundamentals; social deferred.**

| Input        | v1 source (starting point)                  | Status     |
| ------------ | ------------------------------------------- | ---------- |
| Price+volume | Alpaca bars (free)                          | In scope   |
| News         | Alpaca / Benzinga headlines                 | In scope   |
| Fundamentals | Financial Modeling Prep / Tiingo / yfinance | In scope   |
| Social media | (X / Reddit / StockTwits)                   | **Deferred** |

In v1, news + fundamentals feed the **qualitative branch's** thesis generation
([ADR-0003](0003-two-branch-alpha-and-validation-asymmetry.md)); the quant
breakout signal itself is price+volume only.

## Consequences

- Near-zero data cost and near-zero slippage concern for v1.
- The swappable broker interface is the seam for the future multi-asset roadmap
  ([ADR-0007](0007-build-sequencing-and-roadmap.md)).
- **Open item:** survivorship-bias-free S&P 100 *historical membership* is not
  trivially free; the backtester must either source it or document the limitation
  ([ADR-0003](0003-two-branch-alpha-and-validation-asymmetry.md)).
- Social-media sentiment is added later only if backtests/forward results justify
  the cost and noise.

## Alternatives considered

- **Universe: S&P 500 / liquidity-filtered broad universe** — More breakouts and
  stronger edge in mid-caps, but more data and junk to filter. Deferred to a
  later widening.
- **Strategy: pullback mean-reversion / relative-volume scanner** — Viable swing
  edges, but breakout is more durable and the cleanest volume-led starting point.
- **Broker: Interactive Brokers / Alpaca coded directly** — IBKR is heavier to
  operate; coding Alpaca directly costs refactoring at the first new asset class.
  Rejected in favor of Alpaca behind an interface.
- **Data: lean (price+news only) / full (incl. social)** — Lean idles the
  fundamentals analyst; full front-loads the flakiest, priciest data. Rejected.
