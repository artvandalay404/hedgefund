# 1. Paper-first trading posture

- Status: Accepted
- Date: 2026-06-01
- Deciders: Satwik (Portfolio Manager)

## Context

This is a greenfield, autonomous trading system. The most consequential early
choice is what is actually at stake: real money or simulated, and whose money.
That choice gates regulatory exposure, risk tolerance, how realistic execution
must be, and how dangerous a bug is.

- Trading **other people's money** triggers SEC/state RIA registration and fund
  formation (LP/GP) — a lawyer-and-accountant problem before a coding one.
- Trading **your own money** is legally simple but exposes real capital to a
  brand-new, unproven, autonomous system from day one.

## Decision

Run **paper-first**: trade against live market data with simulated fills and
**zero real capital**. Graduate to real money only after a proven track record,
and treat that graduation as a separate, deliberate project (which reopens the
human-approval question — see [ADR-0002](0002-hybrid-pipeline-architecture.md)).

Outside investors are explicitly **not** contemplated until far later, if ever.

## Consequences

- We can run **fully autonomously** and **simulate any account size** without
  financial risk, optimizing for learning velocity and a clean path to live.
- The entire RIA/fund-formation legal burden is deferred.
- "Realism" becomes a deliberate engineering goal (modeled slippage, spread,
  point-in-time data) since simulated fills can otherwise flatter results.
- A future "going live" effort must add: a real-money broker path, a
  human-approval/oversight model, and a compliance review.

## Alternatives considered

- **Real money, own capital only** — Legally simple, but real losses from a
  day-one bug and no track record to justify the risk. Rejected for v1.
- **Real money, outside investors** — Regulatory and compliance obligations far
  outweigh any benefit at this stage. Rejected.
