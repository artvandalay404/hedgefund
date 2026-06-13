# Architecture block diagram

A visual companion to [`CLAUDE.md`](../CLAUDE.md) and the [ADRs](adr/). It shows
how the conceptual hedge-fund org chart maps onto **one orchestrated,
mostly-deterministic pipeline** ([ADR-0002](adr/0002-hybrid-pipeline-architecture.md)):
**LLMs reason, deterministic code decides and executes.**

> **Legend.** Solid boxes = built (Phase 1 walking skeleton + Phase 2 quant edge gate, [ADR-0007](adr/0007-build-sequencing-and-roadmap.md)).
> Dashed boxes = designed but **not yet built** (qualitative branch, agreement multiplier, quant-researcher authoring loop).
> Phase-1/2 trades **quant-solo only**; the official paper track record opens only after
> the strategy passes the rigorous backtest gate (run `scripts/evaluate_holdout.py`).

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
        claude["Anthropic Claude<br/>(strategy authoring + qualitative branch · future)"]
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

    gate -->|"proposes (Phase 2 — built)"| base
    qthes -.->|"proposes (Phase 3)"| base
    kill --> exec --> attr

    classDef future stroke-dasharray:5 5,fill:#fafafa,color:#888;
    class qualb,qcat,qthes future;
```

---

## 3b. Quant-researcher authoring loop (offline · human-gated · designed)

[ADR-0009](adr/0009-llm-authored-strategy-contract.md) lets an LLM **author**
strategies, not just trade them. The loop is **offline and human-triggered** — it
never runs in the trade pipeline, and it **stops at walk-forward**; touching the
sealed holdout stays the separate, human-gated `evaluate_holdout.py`
([ADR-0008](adr/0008-validation-data-discipline.md),
[ADR-0010](adr/0010-effective-trial-accounting.md)).

```mermaid
flowchart LR
    pm["Portfolio manager<br/>natural-language theory"] --> author
    subgraph research["QUANT RESEARCHER — authoring loop (designed, not built)"]
        author["LLM author · quant_research/author.py<br/>Claude · tool-use → StrategySpec"]
        spec["DSL spec<br/>entry/exit over primitive registry<br/>+ 4-part economic rationale"]
        compile["compile_spec → StrategyBase<br/>quant_research/compiler.py"]
        nbhd["neighbor family<br/>deterministic ±1 step · K-cap"]
        author --> spec --> compile --> nbhd
    end
    nbhd --> wf["WalkForwardCV (generalized)<br/>(config_identity, StrategyBase)<br/>DSR · PBO · effective-N"]
    wf --> report["AuthoringReport<br/>FROZEN — eligible for holdout | FAIL — refine in-sample"]
    report -->|persist trial + returns| db[("trial_log<br/>data-keyed search-N · returns_json")]
    report -.->|human spends holdout_n, separately| holdout["evaluate_holdout.py<br/>(unchanged human gate)"]

    classDef future stroke-dasharray:5 5,fill:#fafafa,color:#888;
    class research,author,spec,compile,nbhd future;
```

> The LLM emits a **spec**, never code; a deterministic compiler/executor runs it
> ([ADR-0002](adr/0002-hybrid-pipeline-architecture.md) boundary holds). Primitives
> are vetted point-in-time-safe Python fns in a registry the LLM only *composes*.
> Every strategy ever tested shares one **data-keyed** search-N counter; one
> authoring run — canonical spec, ±1-step neighbours, and all walk-forward folds
> — charges it a flat **1** (one bet, not N); the participation-ratio eff-N is a
> reported guardrail ([ADR-0010](adr/0010-effective-trial-accounting.md)).

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
| Persistence | `db/models.py` | SQLAlchemy: RunLog, Signal, Order, Position, Trade, EquityCurve, SystemState + BacktestTrial, PartitionCounter, HoldoutEval |
| Reporting | `reporting/email_report.py` | Pre/post-market HTML digests via Resend |
| Config | `config.py` | Settings, risk limits, logging |
| Backtest | `backtest/engine.py` | Event-driven daily-bar backtester (point-in-time, honest stops, cost model) |
| Backtest | `backtest/strategy.py` | StrategyBase + BreakoutStrategy (vectorised signal precomputation) |
| Backtest | `backtest/metrics.py` | Annualised Sharpe, PSR, DSR (Bailey & de Prado), PBO, gate thresholds |
| Backtest | `backtest/validation.py` | WalkForwardCV (expanding window + embargo), HoldoutEvaluator (one-shot) |
| Backtest | `backtest/data.py` | yfinance historical bar loader with disk cache |
| Backtest | `backtest/trial_log.py` | Monotonic partition trial counters + trial/holdout logging |
| Quant research | `quant_research/dsl.py` | StrategySpec (pydantic) + point-in-time primitive registry — _designed_ |
| Quant research | `quant_research/compiler.py` | `compile_spec → StrategyBase` — _designed_ |
| Quant research | `quant_research/neighborhood.py` | Deterministic ±1-step neighbor family (K-cap) for DSR/PBO — _designed_ |
| Quant research | `quant_research/author.py` | LLM author: Anthropic tool-use → validated spec — _designed_ |
| Scripts | `scripts/run_backtest.py` | Walk-forward search over param grid; logs every trial to DB |
| Scripts | `scripts/evaluate_holdout.py` | Human-gated one-shot holdout evaluation; opens official track record |
| Scripts | `scripts/author_strategy.py` | Human-triggered: PM theory → DSL spec → walk-forward → AuthoringReport — _designed_ |

---

_Keep this diagram in sync with the code: per [`CLAUDE.md`](../CLAUDE.md),
update it whenever an architectural change is made._
