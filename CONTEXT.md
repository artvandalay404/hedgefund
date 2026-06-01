# Context: hedgefund

An autonomous, **paper-first** swing-trading system for US mega-caps. It runs two
parallel alpha engines — a **backtested systematic quant branch** and a
**forward-validated discretionary LLM branch** — wrapped in deterministic risk
controls, reporting to the portfolio manager twice a day by email.

The long-term ambition is a multi-asset "AI hedge fund" (equities → options →
prediction markets). This document and the ADRs describe **v1**, which is
deliberately narrow so the rails can be proven before capital or scope grows.

## How the "hedge fund org chart" maps to the system

The fund is described in the language of a real desk — research analysts, quant
researchers, execution traders, a portfolio manager. That org chart is
**conceptual**: it shapes how we reason and how the daily summary reads. The
**implementation is a single orchestrated pipeline of mostly-deterministic
stages with targeted LLM calls**, not a crew of autonomous agents messaging each
other. See [ADR-0002](docs/adr/0002-hybrid-pipeline-architecture.md).

| Org role            | What it actually is in the system                                            |
| ------------------- | ---------------------------------------------------------------------------- |
| Quant researcher    | The backtester + the systematic strategies (deterministic code).             |
| Research analyst    | The qualitative branch — an LLM that studies catalysts and writes theses.    |
| Execution trader    | The order/risk module that places bracket orders (no live liquidity-mgmt yet).|
| Portfolio manager   | You. You receive the summaries and hold the kill switch. Not in the loop.    |
| Reporter            | The LLM step that writes the pre-/post-market email digests.                 |

## Glossary

Use these terms exactly; avoid the synonyms noted.

### Posture
- **Paper-first** — Trading against live market data with **simulated fills** and
  **zero real capital**. The default and only mode for v1. ([ADR-0001](docs/adr/0001-paper-first-trading-posture.md))
- **Going live** — The future transition to real capital. Gated on a proven
  track record; reopens the human-approval question. Out of scope for v1.
- **Kill switch** — A code-enforced halt on new entries (and optionally a flatten)
  triggered by drawdown limits. Binds the whole system regardless of branch.

### Architecture
- **Branch** / **alpha branch** — One of the two independent sources of trade
  ideas. There are exactly two: the **quant branch** and the **qualitative
  branch**. Each can **originate** a trade.
- **Quant branch** — Systematic, price/volume/indicator-driven strategies. Every
  quant strategy must clear the rigorous backtest before it trades. (Avoid:
  "the algo", "the model" — be specific.)
- **Qualitative branch** — An LLM that studies catalysts (earnings surprises,
  guidance, analyst revisions, news) and forms forward-looking buy/sell
  **theses**. Cannot be honestly backtested; validated forward only.
- **Originate** — To propose a trade. Both branches originate; **only
  deterministic code executes**. No live LLM call is ever the literal buy/sell
  trigger. ([ADR-0002](docs/adr/0002-hybrid-pipeline-architecture.md))
- **Pipeline stage** — A step in the twice-daily orchestrated run. Most stages
  are deterministic code; a few are LLM calls (thesis generation, reporting).

### Strategy & market
- **Swing trade** — A position intended to be held days to a couple of weeks.
- **Universe** — The set of symbols scanned each cycle. v1 universe is the
  **S&P 100**.
- **Volume-confirmed breakout** — v1's first quant strategy: enter on a new
  N-day high accompanied by volume well above its trailing average; stop below
  the breakout level; exit on target or trailing stop.
- **Bracket order** — An entry order submitted together with its stop and target,
  enforced **broker-side** so intraday risk is handled without a live-monitoring
  loop. ([ADR-0005](docs/adr/0005-trading-scope-universe-strategy-broker-data.md))
- **Pre-market cycle / post-market cycle** — The two scheduled runs per trading
  day. Pre-market plans and places orders; post-market reviews and reports.

### Risk
- **Fixed-fractional sizing** — Position size derived from the stop distance so
  that every trade risks the same fixed fraction of equity. ([ADR-0004](docs/adr/0004-risk-management-framework.md))
- **Heat** / **portfolio heat** — The sum of open per-trade risk across all
  positions; capped.
- **Base size** — The position size the deterministic risk model assigns before
  any branch-agreement adjustment.
- **Agreement multiplier** — The factor applied to base size when branches
  interact: ~1× for a solo proposal, ~1.5× (capped) when both branches agree
  (**consensus**), and a cut-to-zero **veto** on conflict.

### Validation & attribution
- **Rigorous backtest** — Walk-forward + an untouched out-of-sample holdout,
  point-in-time data, modeled slippage/spread, and survivorship-bias-free
  universe membership. The gate every quant strategy must pass. ([ADR-0003](docs/adr/0003-two-branch-alpha-and-validation-asymmetry.md))
- **Forward validation** — Earning trust by live paper performance because a
  strategy (the qualitative branch) cannot be honestly backtested.
- **Attribution bucket** — One of **quant-solo**, **qual-solo**, or **consensus**.
  Every trade is tagged so each branch's standalone contribution is measurable.
- **Survivorship bias** — The error of backtesting on *today's* index members,
  silently testing only the winners that survived into the index.
- **Point-in-time data** — Data restricted to what was knowable at the decision
  timestamp; the defense against lookahead bias.

### Operations
- **Walking skeleton** — The thinnest end-to-end loop (broker + data + risk +
  pipeline + email) that trades paper unattended. Proves the plumbing; its
  results are **explicitly not** counted as track record. ([ADR-0007](docs/adr/0007-build-sequencing-and-roadmap.md))
- **Official track record** — Paper performance that *counts*, beginning only
  after the quant branch passes its rigorous backtest gate.

## Current status

**Design complete; nothing built.** Build proceeds in three phases — walking
skeleton → quant edge gate → qualitative branch — per
[ADR-0007](docs/adr/0007-build-sequencing-and-roadmap.md).

## Decision record

All architectural decisions live in [`docs/adr/`](docs/adr/). Read the ADRs that
touch the area you're working in before changing it; if your change contradicts
one, surface that rather than silently overriding it.
