"""APScheduler entrypoint.

Runs pre-market at 08:30 ET and post-market at 16:30 ET on weekdays.
A minimal HTTP health-check server runs in a daemon thread so Fly.io can
confirm the machine is alive.
"""
from __future__ import annotations

import threading
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from hedgefund.broker.alpaca import AlpacaPaperAdapter
from hedgefund.config import configure_logging, settings
from hedgefund.db.models import Base, engine, get_session, set_state
from hedgefund.pipeline.pre_market import run_pre_market
from hedgefund.pipeline.post_market import run_post_market

configure_logging()
log = structlog.get_logger(__name__)

TZ = "America/New_York"


# ── Health-check HTTP server ──────────────────────────────────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args) -> None:
        pass  # suppress default access logs


def _start_health_server(port: int = 8080) -> None:
    server = HTTPServer(("", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("health_server.started", port=port)


# ── Job wrappers ──────────────────────────────────────────────────────────────

def _run_pre_market() -> None:
    broker = AlpacaPaperAdapter()
    # Record daily start equity once per day
    session = get_session()
    try:
        today = date.today()
        key = f"daily_start_{today}"
        from hedgefund.db.models import get_state as _gs
        existing = _gs(session, key)
        if not existing:
            account = broker.get_account()
            set_state(session, key, str(account.equity))
    finally:
        session.close()
    run_pre_market(broker)


def _run_post_market() -> None:
    broker = AlpacaPaperAdapter()
    run_post_market(broker)


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def _init_db() -> None:
    """Create tables if they don't exist (idempotent for SQLite dev; Fly uses alembic)."""
    import os
    if os.environ.get("DATABASE_URL", "").startswith("sqlite"):
        Base.metadata.create_all(engine)
        log.info("db.tables_created", mode="sqlite")


def main() -> None:
    log.info("scheduler.starting")
    _init_db()
    _start_health_server()

    scheduler = BlockingScheduler(timezone=TZ)

    scheduler.add_job(
        _run_pre_market,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=30, timezone=TZ),
        id="pre_market",
        name="Pre-market cycle",
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_post_market,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=TZ),
        id="post_market",
        name="Post-market cycle",
        max_instances=1,
        misfire_grace_time=300,
    )

    log.info(
        "scheduler.running",
        pre_market="08:30 ET mon-fri",
        post_market="16:30 ET mon-fri",
    )
    scheduler.start()


if __name__ == "__main__":
    main()
