# Architecture block diagram

A visual companion to [`CLAUDE.md`](../CLAUDE.md) and the [ADRs](adr/). It shows
how the conceptual hedge-fund org chart maps onto **one orchestrated,
mostly-deterministic pipeline** ([ADR-0002](adr/0002-hybrid-pipeline-architecture.md)):
**LLMs reason, deterministic code decides and executes.**

> **Legend.** Solid boxes = built (Phase 1 walking skeleton, [ADR-0007](adr/0007-build-sequencing-and-roadmap.md)).
> Dashed boxes = designed but **not yet built** (quant backtest gate, qualitative
> branch, agreement multiplier). Phase-1 trades **quant-solo only**; all paper
> results are explicitly **not** track record until the backtest gate is passed.

---

## 1. System context

The runtime is a twice-daily batch on a managed host ([ADR-0006](adr/0006-stack-runtime-and-reporting.md)).
No always-on intraday loop — broker-side bracket orders carry intraday risk
([ADR-0005](adr/0005-trading-scope-universe-strategy-broker-data.md)).

```mermaid
flowchart LR
    subgraph host["Managed host — Fly.io"]
        sched["scheduler.py<br/>APScheduler cron (ET)<br/>+ health-check HTTP"]
        pipe["Pipeline<br/>pre-market 08:30 · post-market 16:30"]
        sched -->|triggers cycles| pipe
    end

    subgraph ext["External services"]
        alpaca["Alpaca<br/>paper broker + market data"]
        resend["Resend<br/>transactional email"]
        claude["Anthropic Claude<br/>(qualitative branch · future)"]
    end

    db[("Postgres / SQLite<br/>durable state")]

    pipe <-->|"bars · orders · fills · account"| alpaca
    pipe -->|"HTML digest"| resend
    pipe <-->|"signals · orders · positions<br/>trades · equity curve · state"| db
    pipe -.->|"theses (future)"| claude
    resend -->|"pre/post-market email"| pm["Portfolio manager<br/>(notified, not in loop)"]

    classDef future stroke-dasharray:5 5,fill:#fafafa,color:#888;
    class claude future;
```

---

## 2. Twice-daily pipeline (org chart → stages)

Each "role" in the fund is a **pipeline stage**, not an autonomous agent. The
pre-market cycle plans and places orders; the post-market cycle reconciles and
reports.

```mermaid
flowchart TB
    start(["Scheduler fires<br/>(pre or post market)"]) --> acct

    subgraph pre["PRE-MARKET CYCLE — pipeline/pre_market.py"]
        direction TB
        acct["1 · Account snapshot<br/>broker.get_account()"]
        ks1{"2 · Kill-switch check<br/>risk/sizing.check_kill_switch"}
        scan["3 · Scan universe<br/>data.get_universe_bars → signals.scan_breakouts<br/><i>quant branch — volume-confirmed breakout</i>"]
        qual["Qualitative branch<br/>Claude thesis generation"]
        size["4-5 · Size + filter<br/>risk/sizing.compute_size<br/>fixed-fractional · caps · agreement mult."]
        place["Place bracket orders<br/>broker.place_bracket_order"]
        persist1["Persist signals + orders"]
        email1["6 · Pre-market email<br/>reporting.build_pre_market_html"]

        acct --> ks1
        ks1 -->|"halted: skip entries,<br/>still report"| email1
        ks1 -->|active| scan
        scan --> size
        qual -.->|propose| size
        size --> place --> persist1 --> email1
    end

    email1 --> midday(["… market hours …<br/>broker enforces stops/targets"]) --> post

    subgraph post["POST-MARKET CYCLE — pipeline/post_market.py"]
        direction TB
        acct2["1 · Account snapshot"]
        sync["2-3 · Sync orders + positions<br/>reconcile fills, close gone positions<br/>→ record Trade (attribution bucket)"]
        eq["4 · Update equity curve<br/>daily P&L · heat · open positions"]
        ks2["5 · Update peak equity<br/>+ re-check kill switch"]
        email2["6 · Post-market email<br/>fills · P&L · equity · attribution"]

        acct2 --> sync --> eq --> ks2 --> email2
    end

    email2 --> done(["Cycle complete<br/>RunLog status=success"])

    classDef future stroke-dasharray:5 5,fill:#fafafa,color:#888;
    class qual future;
```

---

## 3. Two-branch alpha model + deterministic risk gate

Both branches **originate** trades; **only deterministic code executes**. The
risk model and kill switch are the **final authority** and bind both branches
unconditionally ([ADR-0003](adr/0003-two-branch-alpha-and-validation-asymmetry.md),
[ADR-0004](adr/0004-risk-management-framework.md)).

```mermaid
flowchart TB
    subgraph quant["QUANT BRANCH — built"]
        qstrat["Volume-confirmed breakout<br/>signals.scan_breakouts<br/>price+volume only"]
        gate{"Rigorous backtest gate<br/>walk-forward · holdout · PIT data"}
        qstrat --> gate
    end

    subgraph qualb["QUALITATIVE BRANCH — future"]
        qcat["Catalyst scan<br/>news · fundamentals · earnings"]
        qthes["LLM thesis<br/>(structured, evidence-cited)"]
        qcat --> qthes
    end

    subgraph risk["DETERMINISTIC RISK MODEL — risk/sizing.py"]
        base["Base size<br/>fixed-fractional: 0.5% equity / stop distance"]
        agree["Agreement multiplier<br/>solo 1× · consensus 1.5× · conflict → veto 0×"]
        caps["Hard caps<br/>≤8 positions · ≤15% notional/name · ≤4% heat"]
        kill["Kill switch<br/>−10% drawdown · −3% daily loss"]
        base --> agree --> caps --> kill
    end

    exec["Execution — broker.place_bracket_order<br/>entry + stop + target, broker-enforced"]
    attr[("Attribution buckets<br/>quant-solo · qual-solo · consensus<br/>tagged on every Trade")]

    gate -->|"proposes (Phase 2)"| base
    qthes -.->|"proposes (Phase 3)"| base
    kill --> exec --> attr

    classDef future stroke-dasharray:5 5,fill:#fafafa,color:#888;
    class qualb,qcat,qthes future;
```

---

## 4. Module map

| Layer | Module | Responsibility |
| ----- | ------ | -------------- |
| Orchestration | `scheduler.py` | APScheduler cron (08:30 / 16:30 ET, mon–fri) + health server |
| Pipeline | `pipeline/pre_market.py` | Scan → size → place bracket orders → email |
| Pipeline | `pipeline/post_market.py` | Reconcile fills/positions → equity curve → kill switch → email |
| Pipeline | `pipeline/signals.py` | Volume-confirmed breakout scanner (quant branch) |
| Risk | `risk/sizing.py` | Fixed-fractional sizing, caps, agreement multiplier, kill switch |
| Broker | `broker/interface.py` | Swappable `BrokerInterface` protocol (the multi-asset seam) |
| Broker | `broker/alpaca.py` | Alpaca paper adapter |
| Data | `data/market.py` | Daily bars from Alpaca |
| Data | `data/universe.py` | S&P 100 universe (static snapshot; PIT membership is future) |
| Persistence | `db/models.py` | SQLAlchemy: RunLog, Signal, Order, Position, Trade, EquityCurve, SystemState |
| Reporting | `reporting/email_report.py` | Pre/post-market HTML digests via Resend |
| Config | `config.py` | Settings, risk limits, logging |

---

_Keep this diagram in sync with the code: per [`CLAUDE.md`](../CLAUDE.md),
update it whenever an architectural change is made._
