# 2. Hybrid architecture: LLMs reason, code decides — as a pipeline

- Status: Accepted
- Date: 2026-06-01
- Deciders: Satwik (Portfolio Manager)

## Context

The fund is conceived as an org of agents (research analysts, quant researchers,
execution traders). Two failure modes loom:

1. Letting an **LLM make the literal buy/sell call**. LLMs are non-deterministic,
   weak at numerical precision, prone to hallucination on exactly the numbers
   that matter, and effectively impossible to backtest.
2. Building a **crew of autonomous agents** that message each other — slow,
   costly, hard to debug, and mostly wrapping code that should run directly.

## Decision

**Hybrid control.** LLMs *reason* (research, sentiment/catalyst synthesis,
strategy proposals, report writing); **deterministic code decides and executes**
(signal computation, position sizing, risk enforcement, order placement,
backtesting). **No live LLM call is ever the literal buy/sell trigger.**

**Org chart = pipeline stages, not a crew.** The system is one orchestrated,
mostly-deterministic pipeline. Each "role" is a stage; a few stages are targeted
LLM calls (qualitative thesis generation, the daily report). One scheduler runs
the stages in sequence per cycle.

The system runs **twice-daily in batch**: a pre-market cycle plans and places
orders, a post-market cycle reviews and reports. There is **no always-on
intraday monitoring loop** — broker-side bracket orders handle intraday risk
(see [ADR-0005](0005-trading-scope-universe-strategy-broker-data.md)).

Operation is **fully autonomous in paper**, backed by a code-enforced **kill
switch** (see [ADR-0004](0004-risk-management-framework.md)). The portfolio
manager receives summaries but is **not in the execution loop**; the summary is
a notification, not an approval gate. An approval gate is reconsidered only at
the real-money transition ([ADR-0001](0001-paper-first-trading-posture.md)).

## Consequences

- The decision logic is **reproducible, testable, and backtestable**; LLM
  variability is confined to research and prose.
- Cheap and debuggable: LLM cost is a handful of calls twice a day.
- The "agent" experience lives in *how the system reasons and reports*, not in a
  literal multi-agent runtime.
- A genuine open-ended-reasoning need (e.g., the qualitative branch) is handled
  as a **well-scoped LLM stage with a structured output contract**, not a free-
  roaming agent. See [ADR-0003](0003-two-branch-alpha-and-validation-asymmetry.md).

## Alternatives considered

- **LLM makes live trade calls** — Maximally "agentic", but non-deterministic,
  unbacktestable, hallucination-exposed. Rejected.
- **True multi-agent crew** — Cinematic but over-engineered; revisit only if a
  role genuinely needs open-ended reasoning beyond a single scoped call.
- **Single agent with tools deciding control flow** — Hands the schedule to an
  LLM where a fixed deterministic routine is safer and cheaper. Rejected.
- **Continuous intraday monitoring** — Needs paid real-time data and 24/x infra;
  unnecessary when holds last days and stops are broker-enforced. Rejected.
