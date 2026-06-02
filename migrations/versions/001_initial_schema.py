"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "run_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cycle", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("notes", sa.Text()),
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("run_logs.id")),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("branch", sa.String(20), nullable=False, server_default="quant"),
        sa.Column("direction", sa.String(10), nullable=False, server_default="long"),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_price", sa.Float(), nullable=False),
        sa.Column("target_price", sa.Float(), nullable=False),
        sa.Column("base_qty", sa.Integer(), nullable=False),
        sa.Column("final_qty", sa.Integer(), nullable=False),
        sa.Column("agreement_multiplier", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime()),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id")),
        sa.Column("broker_order_id", sa.String(100), nullable=False, unique=True),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("order_type", sa.String(20), nullable=False, server_default="market"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stop_price", sa.Float()),
        sa.Column("target_price", sa.Float()),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(10), nullable=False, unique=True),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("avg_entry_price", sa.Float(), nullable=False),
        sa.Column("current_price", sa.Float()),
        sa.Column("branch", sa.String(20), nullable=False),
        sa.Column("stop_price", sa.Float(), nullable=False),
        sa.Column("target_price", sa.Float(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("branch", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=False),
        sa.Column("entry_at", sa.DateTime(), nullable=False),
        sa.Column("exit_at", sa.DateTime(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("exit_reason", sa.String(50)),
    )

    op.create_table(
        "equity_curve",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False, unique=True),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("daily_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("open_positions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("portfolio_heat", sa.Float(), nullable=False, server_default="0"),
    )

    op.create_table(
        "system_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(50), nullable=False, unique=True),
        sa.Column("value", sa.Text()),
        sa.Column("updated_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("system_state")
    op.drop_table("equity_curve")
    op.drop_table("trades")
    op.drop_table("positions")
    op.drop_table("orders")
    op.drop_table("signals")
    op.drop_table("run_logs")
