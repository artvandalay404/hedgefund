"""Add Phase 2 backtest validation tables (ADR-0008)

Revision ID: 002
Revises: 001
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "partition_counters",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("partition_name", sa.String(100), unique=True, nullable=False),
        sa.Column("search_n", sa.Integer, nullable=False, server_default="0"),
        sa.Column("holdout_n", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime),
    )

    op.create_table(
        "backtest_trials",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("strategy_name", sa.String(100), nullable=False),
        sa.Column("params_json", sa.Text, nullable=False),
        sa.Column("partition_name", sa.String(100), nullable=False),
        sa.Column("search_n_at_run", sa.Integer, nullable=False),
        sa.Column("annualised_sharpe", sa.Float),
        sa.Column("annualised_return", sa.Float),
        sa.Column("max_drawdown", sa.Float),
        sa.Column("n_trades", sa.Integer, nullable=False, server_default="0"),
        sa.Column("returns_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "holdout_evals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("strategy_name", sa.String(100), nullable=False),
        sa.Column("params_json", sa.Text, nullable=False),
        sa.Column("holdout_partition", sa.String(100), nullable=False),
        sa.Column("holdout_n_at_eval", sa.Integer, nullable=False),
        sa.Column("search_n_at_eval", sa.Integer, nullable=False),
        sa.Column("annualised_sharpe", sa.Float),
        sa.Column("annualised_return", sa.Float),
        sa.Column("max_drawdown", sa.Float),
        sa.Column("psr", sa.Float),
        sa.Column("dsr", sa.Float),
        sa.Column("n_trades", sa.Integer),
        sa.Column("passed_gate", sa.Boolean),
        sa.Column("notes", sa.Text),
        sa.Column("evaluated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("holdout_evals")
    op.drop_table("backtest_trials")
    op.drop_table("partition_counters")
