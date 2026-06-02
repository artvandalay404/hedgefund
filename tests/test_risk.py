"""Unit tests for risk/sizing.py (ADR-0004).

Deterministic code: no broker, no DB, no network — just math.
"""
import pytest

from hedgefund.config import Settings
from hedgefund.risk.sizing import KillSwitchStatus, check_kill_switch, compute_size


# A fast minimal config to avoid loading .env during tests
_cfg = Settings(
    apca_api_key_id="test",
    apca_api_secret_key="test",
    resend_api_key="test",
    email_to="test@example.com",
    risk_per_trade=0.005,
    max_positions=8,
    max_notional_pct=0.15,
    max_heat=0.04,
    kill_switch_drawdown=0.10,
    kill_switch_daily_loss=0.03,
)

EQUITY = 100_000.0


class TestComputeSize:
    def test_basic_long(self):
        # risk $500, stop distance $10 → 50 shares
        result = compute_size(EQUITY, entry_price=110.0, stop_price=100.0,
                              open_positions=0, portfolio_heat=0.0, cfg=_cfg)
        assert not result.rejected
        assert result.base_qty == 50
        assert result.final_qty == 50
        assert result.agreement_multiplier == 1.0
        assert abs(result.risk_amount - 500.0) < 1.0

    def test_consensus_multiplier(self):
        result = compute_size(EQUITY, 110.0, 100.0, 0, 0.0,
                              agreement="consensus", cfg=_cfg)
        assert not result.rejected
        assert result.final_qty == 75  # 50 × 1.5
        assert result.agreement_multiplier == 1.5

    def test_conflict_veto(self):
        result = compute_size(EQUITY, 110.0, 100.0, 0, 0.0,
                              agreement="conflict", cfg=_cfg)
        assert result.rejected
        assert result.final_qty == 0
        assert "conflict" in result.reject_reason

    def test_max_positions_cap(self):
        result = compute_size(EQUITY, 110.0, 100.0, open_positions=8,
                              portfolio_heat=0.0, cfg=_cfg)
        assert result.rejected
        assert "max_positions" in result.reject_reason

    def test_notional_cap(self):
        # Wide stop ($1) → huge raw qty; notional cap must clamp it
        result = compute_size(EQUITY, 100.0, 99.0, 0, 0.0, cfg=_cfg)
        assert not result.rejected
        max_notional = EQUITY * _cfg.max_notional_pct  # $15,000
        assert result.notional <= max_notional + 1.0

    def test_heat_cap(self):
        # Already at max heat
        result = compute_size(EQUITY, 110.0, 100.0, 0,
                              portfolio_heat=EQUITY * _cfg.max_heat, cfg=_cfg)
        assert result.rejected
        assert "heat_cap" in result.reject_reason

    def test_zero_stop_distance_rejected(self):
        result = compute_size(EQUITY, 100.0, 100.0, 0, 0.0, cfg=_cfg)
        assert result.rejected

    def test_partial_heat_allowed(self):
        # 2% heat used, 2% remaining — trade should succeed with reduced size
        result = compute_size(EQUITY, 110.0, 100.0, 0,
                              portfolio_heat=EQUITY * 0.02, cfg=_cfg)
        assert not result.rejected
        # Total heat after this trade must not exceed max_heat
        total = EQUITY * 0.02 + result.risk_amount
        assert total <= EQUITY * _cfg.max_heat + 1.0


class TestKillSwitch:
    def test_not_triggered_at_start(self):
        ks = check_kill_switch(EQUITY, EQUITY, EQUITY, cfg=_cfg)
        assert not ks.triggered

    def test_drawdown_triggers(self):
        # 10% drawdown from peak → trigger
        ks = check_kill_switch(90_000, 100_000, 100_000, cfg=_cfg)
        assert ks.triggered
        assert "drawdown" in ks.reason

    def test_daily_loss_triggers(self):
        ks = check_kill_switch(97_000, 100_000, 100_000, cfg=_cfg)
        assert ks.triggered
        assert "daily loss" in ks.reason

    def test_small_drawdown_not_triggered(self):
        ks = check_kill_switch(95_001, 100_000, 100_000, cfg=_cfg)
        # daily loss = 4.999% > 3%, drawdown = 4.999% < 10% → daily_loss triggers
        assert ks.triggered

    def test_no_trigger_below_thresholds(self):
        # 1% drawdown, 1% daily loss
        ks = check_kill_switch(99_000, 100_000, 99_500, cfg=_cfg)
        assert not ks.triggered
