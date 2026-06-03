"""Persistent trial counters and per-trial logging (ADR-0008).

Every configuration evaluated against a data partition increments search_n for
that partition.  search_n is monotonic and never decrements — the data
remembers every attempt.  holdout_n must stay ≈ 1; modifying the strategy and
retesting against the same holdout is the forbidden move.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from hedgefund.db.models import (
    BacktestTrial,
    HoldoutEval,
    PartitionCounter,
    get_session,
    utcnow,
)


class TrialLogger:
    """Log backtest trials and manage partition trial counters."""

    def __init__(self, session: Session | None = None):
        self._session = session
        self._owns_session = session is None

    def __enter__(self) -> "TrialLogger":
        if self._owns_session:
            self._session = get_session()
        return self

    def __exit__(self, *_) -> None:
        if self._owns_session and self._session:
            self._session.close()

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("TrialLogger not entered as context manager")
        return self._session

    # ── search-N ─────────────────────────────────────────────────────────────

    def increment_search_n(self, partition_name: str) -> int:
        """Increment and return the search_n counter for a partition."""
        row = (
            self.session.query(PartitionCounter)
            .filter_by(partition_name=partition_name)
            .first()
        )
        if row is None:
            row = PartitionCounter(partition_name=partition_name, search_n=0, holdout_n=0)
            self.session.add(row)
        row.search_n += 1
        row.updated_at = utcnow()
        self.session.commit()
        return row.search_n

    def get_search_n(self, partition_name: str) -> int:
        row = (
            self.session.query(PartitionCounter)
            .filter_by(partition_name=partition_name)
            .first()
        )
        return row.search_n if row else 0

    def increment_holdout_n(self, partition_name: str) -> int:
        """Increment and return holdout_n.  Caller must check the returned value."""
        row = (
            self.session.query(PartitionCounter)
            .filter_by(partition_name=partition_name)
            .first()
        )
        if row is None:
            row = PartitionCounter(partition_name=partition_name, search_n=0, holdout_n=0)
            self.session.add(row)
        row.holdout_n += 1
        row.updated_at = utcnow()
        self.session.commit()
        return row.holdout_n

    # ── trial logging ─────────────────────────────────────────────────────────

    def log_trial(
        self,
        strategy_name: str,
        params: dict,
        partition_name: str,
        search_n: int,
        annualised_sharpe: float,
        annualised_return: float,
        max_drawdown: float,
        n_trades: int,
        returns: list[float],
    ) -> int:
        """Persist one trial result; returns the new row id."""
        trial = BacktestTrial(
            strategy_name=strategy_name,
            params_json=json.dumps(params, sort_keys=True),
            partition_name=partition_name,
            search_n_at_run=search_n,
            annualised_sharpe=annualised_sharpe,
            annualised_return=annualised_return,
            max_drawdown=max_drawdown,
            n_trades=n_trades,
            returns_json=json.dumps([round(r, 8) for r in returns]),
            created_at=utcnow(),
        )
        self.session.add(trial)
        self.session.commit()
        return trial.id

    def log_holdout_eval(
        self,
        strategy_name: str,
        params: dict,
        holdout_partition: str,
        holdout_n: int,
        search_n: int,
        annualised_sharpe: float,
        annualised_return: float,
        max_drawdown: float,
        psr: float,
        dsr: float,
        n_trades: int,
        passed_gate: bool,
        notes: str = "",
    ) -> int:
        row = HoldoutEval(
            strategy_name=strategy_name,
            params_json=json.dumps(params, sort_keys=True),
            holdout_partition=holdout_partition,
            holdout_n_at_eval=holdout_n,
            search_n_at_eval=search_n,
            annualised_sharpe=annualised_sharpe,
            annualised_return=annualised_return,
            max_drawdown=max_drawdown,
            psr=psr,
            dsr=dsr,
            n_trades=n_trades,
            passed_gate=passed_gate,
            notes=notes,
            evaluated_at=utcnow(),
        )
        self.session.add(row)
        self.session.commit()
        return row.id
