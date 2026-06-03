"""Post-market cycle: review fills → update state → report (ADR-0002).

Runs at 16:30 ET on weekdays.  Reads broker fills, updates the DB, records
the equity curve, checks the kill switch, then sends the recap email.
"""
from __future__ import annotations

from datetime import date

import structlog

from hedgefund.broker.interface import BrokerInterface
from hedgefund.config import settings
from hedgefund.db.models import (
    EquityCurve, Order, Position, RunLog, Trade, get_session, get_state, set_state,
    utcnow,
)
from hedgefund.reporting.email_report import build_post_market_html, send_email
from hedgefund.risk.sizing import check_kill_switch

log = structlog.get_logger(__name__)


def run_post_market(broker: BrokerInterface) -> None:
    today = date.today()
    date_str = today.strftime("%A, %B %-d %Y")
    session = get_session()

    run = RunLog(cycle="post_market", started_at=utcnow())
    session.add(run)
    session.commit()
    log.info("cycle.start", cycle="post_market", date=str(today))

    try:
        # ── 1. Account snapshot ───────────────────────────────────────────────
        account = broker.get_account()
        equity = account.equity
        log.info("account", equity=equity)

        # ── 2. Fetch broker orders and sync status ────────────────────────────
        broker_orders = broker.get_orders(status="all")
        broker_order_map = {o.broker_id: o for o in broker_orders}

        # Update order statuses in DB
        db_orders = session.query(Order).all()
        fills_today = []
        for db_order in db_orders:
            broker_order = broker_order_map.get(db_order.broker_order_id)
            if broker_order and broker_order.status != db_order.status:
                db_order.status = broker_order.status
                db_order.updated_at = utcnow()
                if broker_order.status == "filled":
                    fills_today.append({
                        "symbol": db_order.symbol,
                        "side": db_order.side,
                        "qty": db_order.qty,
                        "filled_avg_price": broker_order.filled_avg_price,
                        "status": broker_order.status,
                    })

        session.commit()

        # ── 3. Sync positions with broker ─────────────────────────────────────
        broker_positions = broker.get_positions()
        broker_pos_map = {p.symbol: p for p in broker_positions}

        # Remove closed positions from DB
        db_positions = session.query(Position).all()
        for db_pos in db_positions:
            if db_pos.symbol not in broker_pos_map:
                # Position closed — record trade
                _record_closed_trade(session, db_pos, today)
                session.delete(db_pos)
            else:
                # Update current price
                bp = broker_pos_map[db_pos.symbol]
                db_pos.current_price = bp.current_price
                db_pos.updated_at = utcnow()

        # Add any new positions opened today
        existing_symbols = {p.symbol for p in session.query(Position).all()}
        for bp in broker_positions:
            if bp.symbol not in existing_symbols:
                # Find stop/target from today's orders
                order = (
                    session.query(Order)
                    .filter_by(symbol=bp.symbol, side="buy")
                    .order_by(Order.submitted_at.desc())
                    .first()
                )
                session.add(Position(
                    symbol=bp.symbol,
                    qty=bp.qty,
                    avg_entry_price=bp.avg_entry_price,
                    current_price=bp.current_price,
                    branch="quant-solo",
                    stop_price=order.stop_price if order else bp.avg_entry_price * 0.98,
                    target_price=order.target_price if order else bp.avg_entry_price * 1.04,
                    opened_at=utcnow(),
                    updated_at=utcnow(),
                ))

        session.commit()

        # ── 4. Update equity curve ────────────────────────────────────────────
        prev_equity_row = (
            session.query(EquityCurve)
            .order_by(EquityCurve.date.desc())
            .first()
        )
        daily_start_str = get_state(session, f"daily_start_{today}", str(equity))
        daily_start = float(daily_start_str)
        daily_pnl = equity - daily_start

        open_positions_now = session.query(Position).count()
        db_positions_now = session.query(Position).all()
        stop_map = {p.symbol: p.stop_price for p in db_positions_now}
        portfolio_heat = sum(
            p.qty * max(0.0, (p.current_price or p.avg_entry_price) - stop_map.get(p.symbol, 0))
            for p in db_positions_now
            if p.symbol in stop_map
        )

        existing_curve = session.query(EquityCurve).filter_by(date=today).first()
        if existing_curve:
            existing_curve.equity = equity
            existing_curve.daily_pnl = daily_pnl
            existing_curve.open_positions = open_positions_now
            existing_curve.portfolio_heat = portfolio_heat
        else:
            session.add(EquityCurve(
                date=today,
                equity=equity,
                daily_pnl=daily_pnl,
                open_positions=open_positions_now,
                portfolio_heat=portfolio_heat,
            ))
        session.commit()

        # ── 5. Update peak equity and kill-switch state ───────────────────────
        peak_str = get_state(session, "peak_equity", str(equity))
        peak_equity = max(float(peak_str), equity)
        set_state(session, "peak_equity", str(peak_equity))

        ks = check_kill_switch(equity, peak_equity, daily_start)
        if ks.triggered:
            log.warning("kill_switch.triggered", reason=ks.reason)

        # ── 6. Send post-market email ─────────────────────────────────────────
        pos_dicts = [
            {
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_entry_price": p.avg_entry_price,
                "current_price": p.current_price,
                "unrealized_pnl": p.qty * ((p.current_price or p.avg_entry_price) - p.avg_entry_price),
            }
            for p in db_positions_now
        ]

        recent_rows = (
            session.query(EquityCurve)
            .order_by(EquityCurve.date.desc())
            .limit(5)
            .all()
        )
        recent_equity = [
            {"date": str(r.date), "equity": r.equity, "daily_pnl": r.daily_pnl}
            for r in recent_rows
        ]

        html = build_post_market_html(
            date_str=date_str,
            equity=equity,
            daily_pnl=daily_pnl,
            peak_equity=peak_equity,
            portfolio_heat_pct=portfolio_heat / equity if equity > 0 else 0,
            kill_switch=ks.triggered,
            kill_switch_reason=ks.reason,
            fills_today=fills_today,
            open_positions=pos_dicts,
            recent_equity=recent_equity,
        )
        send_email(f"[HedgeFund] Post-Market Recap — {today}", html)

        run.status = "success"
        run.completed_at = utcnow()
        session.commit()
        log.info("cycle.complete", cycle="post_market", equity=equity, daily_pnl=daily_pnl)

    except Exception as exc:
        run.status = "error"
        run.notes = str(exc)
        run.completed_at = utcnow()
        session.commit()
        log.error("cycle.error", cycle="post_market", error=str(exc))
        raise
    finally:
        session.close()


def _record_closed_trade(session, db_pos: Position, today: date) -> None:
    """Record a completed trade when a position disappears from the broker."""
    last_order = (
        session.query(Order)
        .filter_by(symbol=db_pos.symbol)
        .order_by(Order.updated_at.desc())
        .first()
    )
    exit_price = db_pos.current_price or db_pos.avg_entry_price
    realized_pnl = db_pos.qty * (exit_price - db_pos.avg_entry_price)
    branch = db_pos.branch or "quant-solo"

    session.add(Trade(
        symbol=db_pos.symbol,
        branch=branch,
        direction="long",
        qty=db_pos.qty,
        entry_price=db_pos.avg_entry_price,
        exit_price=exit_price,
        entry_at=db_pos.opened_at,
        exit_at=utcnow(),
        realized_pnl=realized_pnl,
        exit_reason="broker_closed",
    ))
    log.info(
        "trade.closed",
        symbol=db_pos.symbol,
        pnl=realized_pnl,
        branch=branch,
    )
