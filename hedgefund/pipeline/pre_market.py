"""Pre-market cycle: scan → size → place orders (ADR-0002).

Runs at 08:30 ET on weekdays.  Orders are bracket orders placed before the
open; the broker enforces stops and targets intraday.
"""
from __future__ import annotations

from datetime import date

import structlog

from hedgefund.broker.interface import BrokerInterface
from hedgefund.config import settings
from hedgefund.data.market import get_universe_bars
from hedgefund.db.models import (
    EquityCurve, Order, Position, RunLog, Signal, get_session, get_state, set_state,
    utcnow,
)
from hedgefund.pipeline.signals import scan_breakouts
from hedgefund.reporting.email_report import (
    build_pre_market_html, send_email,
)
from hedgefund.risk.sizing import KillSwitchStatus, check_kill_switch, compute_size

log = structlog.get_logger(__name__)


def run_pre_market(broker: BrokerInterface) -> None:
    today = date.today()
    date_str = today.strftime("%A, %B %-d %Y")
    session = get_session()

    run = RunLog(cycle="pre_market", started_at=utcnow())
    session.add(run)
    session.commit()
    log.info("cycle.start", cycle="pre_market", date=str(today))

    try:
        # ── 1. Account snapshot ───────────────────────────────────────────────
        account = broker.get_account()
        equity = account.equity
        log.info("account", equity=equity, cash=account.cash)

        # ── 2. Kill-switch check ──────────────────────────────────────────────
        peak_str = get_state(session, "peak_equity", str(equity))
        peak_equity = float(peak_str)
        daily_start_str = get_state(session, f"daily_start_{today}", str(equity))
        daily_start = float(daily_start_str)

        ks = check_kill_switch(equity, peak_equity, daily_start)
        if ks.triggered:
            log.warning("kill_switch.triggered", reason=ks.reason)

        # ── 3. Fetch bars (even if kill switch is on, so we can report scans) ─
        bars_df = get_universe_bars()
        raw_signals = scan_breakouts(bars_df) if not bars_df.empty else []

        # ── 4. Current open positions ─────────────────────────────────────────
        broker_positions = broker.get_positions()
        open_pos_count = len(broker_positions)

        # Build stop map for heat calculation from DB positions
        db_positions = session.query(Position).all()
        stop_map = {p.symbol: p.stop_price for p in db_positions}
        portfolio_heat = sum(
            p.qty * max(0.0, (p.current_price or p.avg_entry_price) - stop_map.get(p.symbol, 0))
            for p in db_positions
            if p.symbol in stop_map
        )

        # ── 5. Size + filter signals ──────────────────────────────────────────
        placed_signals = []
        placed_orders = []
        skipped_symbols = {p.symbol for p in broker_positions}  # no duplicate positions

        if not ks.triggered:
            for raw in raw_signals:
                if raw.symbol in skipped_symbols:
                    log.debug("signal.skip_existing_position", symbol=raw.symbol)
                    continue

                sizing = compute_size(
                    equity=equity,
                    entry_price=raw.entry_price,
                    stop_price=raw.stop_price,
                    open_positions=open_pos_count,
                    portfolio_heat=portfolio_heat,
                    agreement="solo",
                )
                if sizing.rejected:
                    log.info("signal.rejected", symbol=raw.symbol, reason=sizing.reject_reason)
                    continue

                # Persist signal
                sig_row = Signal(
                    run_id=run.id,
                    symbol=raw.symbol,
                    branch=raw.branch,
                    direction=raw.direction,
                    entry_price=raw.entry_price,
                    stop_price=raw.stop_price,
                    target_price=raw.target_price,
                    base_qty=sizing.base_qty,
                    final_qty=sizing.final_qty,
                    agreement_multiplier=sizing.agreement_multiplier,
                )
                session.add(sig_row)
                session.flush()

                # Place bracket order
                try:
                    broker_order = broker.place_bracket_order(
                        symbol=raw.symbol,
                        qty=sizing.final_qty,
                        side="buy",
                        stop_price=raw.stop_price,
                        target_price=raw.target_price,
                    )
                    order_row = Order(
                        signal_id=sig_row.id,
                        broker_order_id=broker_order.broker_id,
                        symbol=raw.symbol,
                        qty=sizing.final_qty,
                        side="buy",
                        status=broker_order.status,
                        stop_price=raw.stop_price,
                        target_price=raw.target_price,
                        submitted_at=utcnow(),
                        updated_at=utcnow(),
                    )
                    session.add(order_row)
                    placed_signals.append({
                        "symbol": raw.symbol,
                        "direction": raw.direction,
                        "entry_price": raw.entry_price,
                        "stop_price": raw.stop_price,
                        "target_price": raw.target_price,
                        "final_qty": sizing.final_qty,
                        "risk_amount": sizing.risk_amount,
                    })
                    placed_orders.append(broker_order)
                    open_pos_count += 1
                    portfolio_heat += sizing.risk_amount
                    skipped_symbols.add(raw.symbol)
                    log.info("order.submitted", symbol=raw.symbol, qty=sizing.final_qty)
                except Exception as exc:
                    log.error("order.failed", symbol=raw.symbol, error=str(exc))

        session.commit()

        # ── 6. Send pre-market email ──────────────────────────────────────────
        pos_dicts = [
            {
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_entry_price": p.avg_entry_price,
                "current_price": p.current_price,
                "unrealized_pnl": p.qty * ((p.current_price or p.avg_entry_price) - p.avg_entry_price),
            }
            for p in broker_positions
        ]
        html = build_pre_market_html(
            date_str=date_str,
            equity=equity,
            peak_equity=peak_equity,
            portfolio_heat_pct=portfolio_heat / equity if equity > 0 else 0,
            kill_switch=ks.triggered,
            kill_switch_reason=ks.reason,
            signals=placed_signals,
            orders_placed=len(placed_orders),
            open_positions=pos_dicts,
        )
        send_email(f"[HedgeFund] Pre-Market Plan — {today}", html)

        run.status = "success"
        run.completed_at = utcnow()
        session.commit()
        log.info("cycle.complete", cycle="pre_market", orders=len(placed_orders))

    except Exception as exc:
        run.status = "error"
        run.notes = str(exc)
        run.completed_at = utcnow()
        session.commit()
        log.error("cycle.error", cycle="pre_market", error=str(exc))
        raise
    finally:
        session.close()
