from datetime import datetime, date as date_type, timezone

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, String, Text, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from hedgefund.config import settings


def utcnow() -> datetime:
    """Naive UTC timestamp — drop-in replacement for the deprecated
    utcnow().  Returns a tz-naive datetime to preserve the storage
    semantics of the existing (timezone-unaware) DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class RunLog(Base):
    __tablename__ = "run_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cycle = Column(String(20), nullable=False)           # pre_market | post_market
    started_at = Column(DateTime, nullable=False, default=utcnow)
    completed_at = Column(DateTime)
    status = Column(String(20), nullable=False, default="running")  # running|success|error
    notes = Column(Text)


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("run_logs.id"))
    symbol = Column(String(10), nullable=False)
    branch = Column(String(20), nullable=False, default="quant")  # quant|qual|consensus
    direction = Column(String(10), nullable=False, default="long")
    entry_price = Column(Float, nullable=False)
    stop_price = Column(Float, nullable=False)
    target_price = Column(Float, nullable=False)
    base_qty = Column(Integer, nullable=False)
    final_qty = Column(Integer, nullable=False)
    agreement_multiplier = Column(Float, nullable=False, default=1.0)
    created_at = Column(DateTime, default=utcnow)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("signals.id"))
    broker_order_id = Column(String(100), unique=True, nullable=False)
    symbol = Column(String(10), nullable=False)
    qty = Column(Integer, nullable=False)
    side = Column(String(10), nullable=False)
    order_type = Column(String(20), nullable=False, default="market")
    status = Column(String(20), nullable=False)
    stop_price = Column(Float)
    target_price = Column(Float)
    submitted_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), unique=True, nullable=False)
    qty = Column(Integer, nullable=False)
    avg_entry_price = Column(Float, nullable=False)
    current_price = Column(Float)
    branch = Column(String(20), nullable=False)  # attribution bucket
    stop_price = Column(Float, nullable=False)
    target_price = Column(Float, nullable=False)
    opened_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False)
    branch = Column(String(20), nullable=False)  # quant-solo | qual-solo | consensus
    direction = Column(String(10), nullable=False)
    qty = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    entry_at = Column(DateTime, nullable=False)
    exit_at = Column(DateTime, nullable=False)
    realized_pnl = Column(Float, nullable=False)
    exit_reason = Column(String(50))            # target | stop | manual


class EquityCurve(Base):
    __tablename__ = "equity_curve"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, unique=True, nullable=False)
    equity = Column(Float, nullable=False)
    daily_pnl = Column(Float, nullable=False, default=0.0)
    open_positions = Column(Integer, nullable=False, default=0)
    portfolio_heat = Column(Float, nullable=False, default=0.0)


class SystemState(Base):
    """Key-value store for persistent system state (peak equity, kill switch, etc.)."""
    __tablename__ = "system_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ── Phase 2: backtesting / validation tables (ADR-0008) ──────────────────────

class PartitionCounter(Base):
    """Monotonic trial counters per data partition (ADR-0008).

    search_n counts every configuration evaluated against the IS/WF partition.
    holdout_n counts holdout evaluations; must stay ≈ 1.
    """
    __tablename__ = "partition_counters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    partition_name = Column(String(100), unique=True, nullable=False)
    search_n = Column(Integer, nullable=False, default=0)
    holdout_n = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=utcnow)


class BacktestTrial(Base):
    """One evaluated (strategy, params, partition) combination."""
    __tablename__ = "backtest_trials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(100), nullable=False)
    params_json = Column(Text, nullable=False)
    partition_name = Column(String(100), nullable=False)
    search_n_at_run = Column(Integer, nullable=False)
    annualised_sharpe = Column(Float)
    annualised_return = Column(Float)
    max_drawdown = Column(Float)
    n_trades = Column(Integer, nullable=False, default=0)
    returns_json = Column(Text, nullable=False)   # JSON array of daily returns
    created_at = Column(DateTime, nullable=False, default=utcnow)


class HoldoutEval(Base):
    """One-shot holdout evaluation result (ADR-0008).

    holdout_n_at_eval must be 1 for the result to be trustworthy.
    """
    __tablename__ = "holdout_evals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(100), nullable=False)
    params_json = Column(Text, nullable=False)
    holdout_partition = Column(String(100), nullable=False)
    holdout_n_at_eval = Column(Integer, nullable=False)
    search_n_at_eval = Column(Integer, nullable=False)
    annualised_sharpe = Column(Float)
    annualised_return = Column(Float)
    max_drawdown = Column(Float)
    psr = Column(Float)
    dsr = Column(Float)
    n_trades = Column(Integer, default=0)
    passed_gate = Column(Boolean)
    notes = Column(Text)
    evaluated_at = Column(DateTime, nullable=False, default=utcnow)


# ── engine / session ──────────────────────────────────────────────────────────

def _make_engine():
    url = settings.database_url
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session():
    return SessionLocal()


def get_state(session, key: str, default: str | None = None) -> str | None:
    row = session.query(SystemState).filter_by(key=key).first()
    return row.value if row else default


def set_state(session, key: str, value: str) -> None:
    row = session.query(SystemState).filter_by(key=key).first()
    if row:
        row.value = value
        row.updated_at = utcnow()
    else:
        session.add(SystemState(key=key, value=value))
    session.commit()
