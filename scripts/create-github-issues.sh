#!/usr/bin/env bash
#
# Creates the labels and issues for the hedgefund build plan (docs/build-plan.md).
# Idempotent on labels; running it twice will create duplicate ISSUES, so run once.
#
# Prereq: gh installed and authenticated (gh auth status).
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh (GitHub CLI) is not installed. brew install gh" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "error: gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

echo "Repo: $(gh repo view --json nameWithOwner -q .nameWithOwner)"

# ---- labels (idempotent) ---------------------------------------------------
create_label() {
  gh label create "$1" --color "$2" --description "$3" >/dev/null 2>&1 \
    || gh label edit "$1" --color "$2" --description "$3" >/dev/null 2>&1 || true
}
echo "Ensuring labels..."
create_label "epic"            "5319e7" "A phase-level tracking issue"
create_label "phase-1"         "0e8a16" "Walking skeleton"
create_label "phase-2"         "fbca04" "Quant edge gate"
create_label "phase-3"         "1d76db" "Qualitative branch"
create_label "ready-for-agent" "0e8a16" "Fully specified, ready for an AFK agent"
create_label "ready-for-human" "d93f0b" "Requires human implementation or a decision"
create_label "needs-triage"    "ededed" "Maintainer needs to evaluate this issue"
create_label "needs-info"      "fef2c0" "Waiting on reporter for more information"

# ---- helper ----------------------------------------------------------------
# new_issue <title> <labels-csv> <body>  -> prints the new issue number
new_issue() {
  local title="$1" labels="$2" body="$3" url num
  url=$(gh issue create --title "$title" --label "$labels" --body "$body")
  num=$(printf '%s' "$url" | grep -oE '[0-9]+$')
  echo "  created #$num  $title" >&2
  printf '%s' "$num"
}

echo "Creating epics..."
E1=$(new_issue "[Epic] Phase 1 — Walking skeleton" "epic,phase-1,needs-triage" \
"Thinnest end-to-end loop trading paper unattended and emailing the PM. Proves plumbing; results do NOT count as track record. See docs/build-plan.md and ADR-0007.

Tasks:
- [ ] Project scaffolding and config
- [ ] Broker interface + Alpaca paper adapter
- [ ] Market data layer (S&P 100 + bars)
- [ ] Postgres state schema and data access
- [ ] Risk and sizing module
- [ ] Orchestrated pre/post-market pipeline
- [ ] Email reporting
- [ ] Deploy to managed host + cron + Postgres
- [ ] End-to-end smoke test (Phase 1 exit)

Exit: on a schedule, reads the universe, places and manages a paper bracket order, persists state to Postgres, and sends both emails from the managed host.")

E2=$(new_issue "[Epic] Phase 2 — Quant edge gate" "epic,phase-2,needs-triage" \
"Validate the volume-confirmed breakout rigorously. Passing the gate opens the official paper track record. See docs/build-plan.md and ADR-0003 / ADR-0007.

Tasks:
- [ ] Event-driven backtester
- [ ] Survivorship-bias-free S&P 100 membership
- [ ] Volume-confirmed breakout strategy
- [ ] Rigorous validation harness
- [ ] Promote validated quant branch to live
- [ ] Quant-solo attribution and reporting

Exit: strategy clears walk-forward + untouched holdout with modeled costs and survivorship-free membership, and is live with quant-solo attribution.")

E3=$(new_issue "[Epic] Phase 3 — Qualitative branch" "epic,phase-3,needs-triage" \
"Add the forward-validated discretionary LLM sleeve. See docs/build-plan.md and ADR-0003.

Tasks:
- [ ] Catalyst data ingestion
- [ ] Define qualitative output contract
- [ ] Qualitative thesis engine
- [ ] Branch arbitration + agreement-multiplier sizing
- [ ] Three-bucket forward attribution + scaling policy
- [ ] Reporting: theses, consensus, attribution

Exit: structured evidence-cited theses flow through agreement-multiplier sizing, with three-bucket attribution in the digests and a defined scaling policy.")

echo "Creating Phase 1 tasks..."
new_issue "Phase 1: Project scaffolding and config" "phase-1,ready-for-agent" \
"Part of #$E1. Python project: dependencies, env/secrets handling, structured logging, config, test harness.

Acceptance:
- A runnable project skeleton with config + secrets loading and a passing test stub.
Ref: ADR-0006." >/dev/null

new_issue "Phase 1: Broker interface + Alpaca paper adapter" "phase-1,ready-for-agent" \
"Part of #$E1. Define a swappable broker interface and implement the Alpaca paper adapter: account, positions, fills, and bracket/OCO order placement.

Acceptance:
- Can place, query, and cancel a paper bracket order through the interface.
Ref: ADR-0005." >/dev/null

new_issue "Phase 1: Market data layer (S&P 100 + bars)" "phase-1,ready-for-agent" \
"Part of #$E1. Maintain the S&P 100 universe list and fetch daily price/volume bars via Alpaca.

Acceptance:
- Returns clean OHLCV for the full universe for a given date range.
Ref: ADR-0005." >/dev/null

new_issue "Phase 1: Postgres state schema and data access" "phase-1,ready-for-agent" \
"Part of #$E1. Schema + access layer for positions, orders, trades (tagged by branch), signals, theses, equity_curve, and run logs.

Acceptance:
- Migrations apply cleanly; every trade row carries an attribution-bucket tag.
Ref: ADR-0003, ADR-0006." >/dev/null

new_issue "Phase 1: Risk and sizing module" "phase-1,ready-for-agent" \
"Part of #$E1. Deterministic fixed-fractional sizing, conservative caps (0.5%/trade, 8 positions, 15%/name, 4% heat), kill switch (-10% from peak, -3% daily), and the base x agreement multiplier.

Acceptance:
- Given a signal + stop + equity, returns a compliant size; caps and kill switch are enforced and unit-tested.
Ref: ADR-0004." >/dev/null

new_issue "Phase 1: Orchestrated pre/post-market pipeline" "phase-1,ready-for-agent" \
"Part of #$E1. Scheduler entrypoints and the ordered cycle steps for pre-market (plan/place) and post-market (review/report).

Acceptance:
- Both cycles run end to end locally against the paper adapter.
Ref: ADR-0002." >/dev/null

new_issue "Phase 1: Email reporting" "phase-1,ready-for-agent" \
"Part of #$E1. Transactional email integration with pre-market (plan) and post-market (recap) HTML templates.

Acceptance:
- Both emails render and send with real cycle data.
Ref: ADR-0006." >/dev/null

new_issue "Phase 1: Deploy to managed host + cron + Postgres" "phase-1,ready-for-human" \
"Part of #$E1. Provision a managed host (Railway/Fly/Render) + Postgres, configure secrets and the two cron schedules, add a healthcheck.

Acceptance:
- Both cycles fire on schedule in production and persist state.
Ref: ADR-0006." >/dev/null

new_issue "Phase 1: End-to-end smoke test (Phase 1 exit)" "phase-1,ready-for-agent" \
"Part of #$E1. Verify the full unattended loop: read universe, place/manage a token paper bracket order, persist state, send both emails from the host.

Acceptance:
- Phase 1 exit criteria in docs/build-plan.md are met. Results explicitly do NOT count as track record." >/dev/null

echo "Creating Phase 2 tasks..."
new_issue "Phase 2: Event-driven backtester" "phase-2,ready-for-agent" \
"Part of #$E2. Event-driven engine with point-in-time data, modeled slippage/spread, and honest intraday stop/target hit modeling.

Acceptance:
- Reproduces a known toy strategy result; no lookahead; costs configurable.
Ref: ADR-0003, ADR-0006." >/dev/null

new_issue "Phase 2: Survivorship-bias-free S&P 100 membership" "phase-2,ready-for-human" \
"Part of #$E2. Source historical S&P 100 constituents (point-in-time) or document the survivorship limitation explicitly. May require buying a dataset.

Acceptance:
- Backtests use as-of membership, or the limitation is documented in CONTEXT.md.
Ref: ADR-0005." >/dev/null

new_issue "Phase 2: Volume-confirmed breakout strategy" "phase-2,ready-for-agent" \
"Part of #$E2. Implement the breakout signal: new N-day high with volume > ~1.5x its trailing average; stop below breakout; target/trailing exit. Parameters configurable.

Acceptance:
- Produces deterministic signals over historical bars for the universe.
Ref: ADR-0005." >/dev/null

new_issue "Phase 2: Rigorous validation harness" "phase-2,ready-for-agent" \
"Part of #$E2. Walk-forward + untouched out-of-sample holdout, performance metrics, and overfit/robustness checks.

Acceptance:
- Produces a pass/fail report against a pre-registered bar; holdout is touched only once.
Ref: ADR-0003." >/dev/null

new_issue "Phase 2: Promote validated quant branch to live" "phase-2,ready-for-agent" \
"Part of #$E2. Wire the validated breakout into the live pipeline and begin the official paper track record.

Acceptance:
- Quant branch originates real paper trades in production; track record clock starts." >/dev/null

new_issue "Phase 2: Quant-solo attribution and reporting" "phase-2,ready-for-agent" \
"Part of #$E2. Track and report the quant-solo attribution bucket in the digests.

Acceptance:
- Digests show quant-solo P&L, hit rate, and equity curve.
Ref: ADR-0003." >/dev/null

echo "Creating Phase 3 tasks..."
new_issue "Phase 3: Catalyst data ingestion" "phase-3,ready-for-agent" \
"Part of #$E3. Ingest earnings dates/surprises, guidance, analyst revisions, and news for the universe.

Acceptance:
- Point-in-time catalyst records available per symbol/date.
Ref: ADR-0005." >/dev/null

new_issue "Phase 3: Define qualitative output contract" "phase-3,ready-for-human" \
"Part of #$E3. Specify the structured thesis the LLM must emit: name, direction, entry/stop/target, horizon, cited catalyst/evidence, calibrated conviction.

Acceptance:
- A documented, validated schema the thesis engine and risk module consume.
Ref: ADR-0003." >/dev/null

new_issue "Phase 3: Qualitative thesis engine" "phase-3,ready-for-agent" \
"Part of #$E3. LLM stage that studies catalysts and emits theses per the output contract. Logs prompt/inputs/evidence for audit.

Acceptance:
- Produces schema-valid theses for the universe each pre-market cycle.
Ref: ADR-0002, ADR-0003." >/dev/null

new_issue "Phase 3: Branch arbitration + agreement-multiplier sizing" "phase-3,ready-for-agent" \
"Part of #$E3. Combine quant and qualitative proposals: solo (1x), consensus (~1.5x capped), conflict (cut/veto), all subject to risk caps.

Acceptance:
- Given both branches proposals, emits a single sized, capped order set with bucket tags.
Ref: ADR-0004." >/dev/null

new_issue "Phase 3: Three-bucket forward attribution + scaling policy" "phase-3,ready-for-agent" \
"Part of #$E3. Track quant-solo / qual-solo / consensus P&L; define how the qualitative sleeve scales up on demonstrated forward value.

Acceptance:
- Per-bucket performance is queryable; a documented scaling rule drives qual size.
Ref: ADR-0003." >/dev/null

new_issue "Phase 3: Reporting — theses, consensus, attribution" "phase-3,ready-for-agent" \
"Part of #$E3. Surface qualitative theses, consensus trades, and per-branch attribution in the email digests.

Acceptance:
- Digests show theses with evidence, consensus names, and three-bucket attribution.
Ref: ADR-0006." >/dev/null

echo "Creating open-decision issue..."
new_issue "Decision: define Phase-2/3 expansion triggers" "needs-triage,ready-for-human" \
"Define the track-record thresholds (e.g., Sharpe, months profitable, max drawdown survived) that unlock more capital, a wider universe, the LLM strategy-factory, and new asset classes (options, then prediction markets).
Ref: ADR-0007." >/dev/null

echo "Done. Review with: gh issue list"
