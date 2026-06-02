from datetime import datetime, date as date_type

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, String, Text, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from hedgefund.config import settings


class Base(DeclarativeBase):
    pass


class RunLog(Base):
    __tablename__ = "run_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cycle = Column(String(20), nullable=False)           # pre_market | post_market
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
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
    created_at = Column(DateTime, default=datetime.utcnow)


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
    submitted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


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
    opened_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


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
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
        row.updated_at = datetime.utcnow()
    else:
        session.add(SystemState(key=key, value=value))
    session.commit()
