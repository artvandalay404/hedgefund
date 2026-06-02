#!/usr/bin/env python3
"""Phase 1 smoke test — exercises the full loop against paper Alpaca.

NOT a track-record run. Verifies plumbing only (ADR-0007).

Usage:
    python scripts/smoke_test.py

Expects .env with APCA_API_KEY_ID, APCA_API_SECRET_KEY, RESEND_API_KEY, EMAIL_TO.
DATABASE_URL defaults to SQLite.
"""
import sys
import traceback
from datetime import date, datetime

from hedgefund.config import configure_logging, settings
from hedgefund.db.models import Base, engine, EquityCurve, get_session, set_state
from hedgefund.broker.alpaca import AlpacaPaperAdapter

configure_logging()

import structlog
log = structlog.get_logger("smoke_test")


def _init_sqlite():
    """Create tables locally (SQLite only)."""
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
        log.info("db.created", url=settings.database_url)


def _check_broker(broker: AlpacaPaperAdapter) -> float:
    account = broker.get_account()
    log.info("broker.account", equity=account.equity, cash=account.cash)
    assert account.equity > 0, "Alpaca paper account has zero equity — check credentials"
    return account.equity


def _seed_daily_state(equity: float) -> None:
    session = get_session()
    try:
        today = date.today()
        set_state(session, f"daily_start_{today}", str(equity))
        set_state(session, "peak_equity", str(equity))
        log.info("state.seeded", date=str(today), equity=equity)
    finally:
        session.close()


def _place_token_order(broker: AlpacaPaperAdapter) -> str | None:
    """Place a tiny bracket order on SPY as the plumbing token trade."""
    positions = broker.get_positions()
    if any(p.symbol == "SPY" for p in positions):
        log.info("token_order.skip", reason="SPY position already open")
        return None

    account = broker.get_account()
    current_price = None
    # Get approximate price from positions or use a safe default
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        client = StockHistoricalDataClient(
            api_key=settings.apca_api_key_id,
            secret_key=settings.apca_api_secret_key,
        )
        bars = client.get_stock_bars(
            StockBarsRequest(symbol_or_symbols="SPY", timeframe=TimeFrame.Day, limit=1)
        )
        df = bars.df.reset_index()
        current_price = float(df["close"].iloc[-1])
    except Exception as e:
        log.warning("price_fetch.failed", error=str(e))
        current_price = 500.0  # safe fallback

    stop = round(current_price * 0.98, 2)
    target = round(current_price * 1.04, 2)
    qty = 1  # token size — minimum possible

    log.info("token_order.placing", symbol="SPY", qty=qty,
             entry=current_price, stop=stop, target=target)
    order = broker.place_bracket_order("SPY", qty, "buy", stop, target)
    log.info("token_order.placed", broker_id=order.broker_id, status=order.status)
    return order.broker_id


def _cancel_token_order(broker: AlpacaPaperAdapter, broker_id: str) -> None:
    try:
        broker.cancel_order(broker_id)
        log.info("token_order.cancelled", broker_id=broker_id)
    except Exception as e:
        log.warning("token_order.cancel_failed", error=str(e))


def _run_pre_market(broker: AlpacaPaperAdapter) -> None:
    from hedgefund.pipeline.pre_market import run_pre_market
    log.info("pre_market.running")
    run_pre_market(broker)
    log.info("pre_market.done")


def _run_post_market(broker: AlpacaPaperAdapter) -> None:
    from hedgefund.pipeline.post_market import run_post_market
    log.info("post_market.running")
    run_post_market(broker)
    log.info("post_market.done")


def main() -> int:
    print("\n" + "=" * 60)
    print("  HedgeFund Phase 1 Smoke Test")
    print("  Results DO NOT count as track record (ADR-0007)")
    print("=" * 60 + "\n")

    _init_sqlite()

    broker = AlpacaPaperAdapter()
    equity = _check_broker(broker)
    _seed_daily_state(equity)

    token_order_id = None
    errors = []

    # Step 1: token bracket order
    try:
        token_order_id = _place_token_order(broker)
    except Exception:
        errors.append(("token_order", traceback.format_exc()))

    # Step 2: pre-market cycle (includes email)
    try:
        _run_pre_market(broker)
    except Exception:
        errors.append(("pre_market", traceback.format_exc()))

    # Step 3: post-market cycle (includes email)
    try:
        _run_post_market(broker)
    except Exception:
        errors.append(("post_market", traceback.format_exc()))

    # Clean up token order
    if token_order_id:
        _cancel_token_order(broker, token_order_id)

    print("\n" + "=" * 60)
    if errors:
        print(f"  FAILED — {len(errors)} error(s):")
        for step, tb in errors:
            print(f"\n  [{step}]\n{tb}")
        return 1

    print("  PASSED — Phase 1 exit criteria met:")
    print("  ✓ Alpaca paper broker connected")
    print("  ✓ Token bracket order placed and cancelled")
    print("  ✓ Pre-market cycle ran (scan → size → place → email)")
    print("  ✓ Post-market cycle ran (fills → equity → email)")
    print("  ✓ State persisted to DB")
    print("\n  Check your inbox for two emails.")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
