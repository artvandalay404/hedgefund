# 6. Tech stack, runtime, and reporting

- Status: Accepted
- Date: 2026-06-01
- Deciders: Satwik (Portfolio Manager)

## Context

The system is a twice-daily batch meant to run **unattended**. What matters is
schedule reliability (orders must be placed around the open), durable state, and
keeping the LLM layer simple given the pipeline architecture
([ADR-0002](0002-hybrid-pipeline-architecture.md)).

## Decision

**Language: Python.** The trading, data, and backtesting ecosystem lives there
(Alpaca SDK, pandas, etc.).

**LLM: Anthropic SDK + Claude**, called directly at the few stages that need it.
Because we chose pipeline-stages over an agent crew, a heavy agent framework is
unnecessary. Expected model split: a cheaper model (e.g., Haiku) for bulk
catalyst scanning/summarization, a stronger model (Sonnet/Opus) for thesis
synthesis and report writing.

**Backtester: a small custom event-driven engine.** Event-driven so intraday
stop/target hits inside the bar are modeled honestly, with point-in-time data and
explicit slippage/spread costs ([ADR-0003](0003-two-branch-alpha-and-validation-asymmetry.md)).

**Runtime: a managed host + cron + Postgres.** A small always-available service
(Railway / Fly.io / Render, or a cheap droplet) runs the pre-/post-market cycles
on a reliable cron; **Postgres** holds durable state (positions, orders,
trades-tagged-by-branch, signals, theses, equity curve, run logs). SQLite is an
acceptable starting point. ~$5–10/mo. Scales cleanly to an always-on intraday
component if ever needed.

**Reporting: email digests.** Formatted HTML email pre-market (the plan: scans,
candidate breakouts, intended orders, risk posture, upcoming strategies) and
post-market (fills, P&L, equity curve, per-bucket attribution, agent notes),
sent via a transactional email API (Resend / Postmark / SES). A chat alert
channel (Telegram/Slack) is added later, purely for urgent events such as a
tripped kill switch.

## Consequences

- Reliable timing before the open; durable, queryable state for attribution.
- Cheap LLM usage (a handful of calls per cycle).
- The email digest is the **product surface** for the portfolio manager — it must
  be genuinely readable, not a log dump.
- A web dashboard is explicitly a later (Phase-2+) addition, not a v1 mechanism.

## Alternatives considered

- **Scheduled GitHub Actions + DB** — Free and zero-infra, but Actions cron is
  best-effort and can be delayed minutes — risky when placing orders at the open.
  Rejected for production cadence (fine for ad-hoc jobs).
- **Local machine + cron/launchd** — Free, but only runs when the machine is
  awake/online; fragile for an unattended system. Fine for early dev only.
- **Chat-push or web dashboard as the primary summary** — Chat is cramped for a
  rich daily digest; a dashboard is pull-not-push and more to build. Deferred.
