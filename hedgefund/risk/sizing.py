"""Fixed-fractional risk sizing and kill-switch enforcement (ADR-0004).

All caps and the kill switch are the final authority and bind regardless of
branch or conviction.  No live LLM call ever touches this module.
"""
from dataclasses import dataclass

from hedgefund.config import Settings, settings as _default_settings


@dataclass
class SizingResult:
    base_qty: int
    final_qty: int
    agreement_multiplier: float
    notional: float
    risk_amount: float          # dollars at risk for this trade
    rejected: bool = False
    reject_reason: str = ""


def compute_size(
    equity: float,
    entry_price: float,
    stop_price: float,
    open_positions: int,
    portfolio_heat: float,      # sum of open per-trade dollar risk
    agreement: str = "solo",   # "solo" | "consensus" | "conflict"
    cfg: Settings | None = None,
) -> SizingResult:
    """Return share count for a new entry, enforcing all caps.

    agreement_multiplier:
      - solo      → 1.0×
      - consensus → 1.5× (both branches agree, subject to all caps)
      - conflict  → 0× veto
    """
    if cfg is None:
        cfg = _default_settings

    # Branch conflict → hard veto
    if agreement == "conflict":
        return SizingResult(0, 0, 0.0, 0.0, 0.0, rejected=True, reject_reason="branch conflict")

    # Position-count cap
    if open_positions >= cfg.max_positions:
        return SizingResult(0, 0, 0.0, 0.0, 0.0, rejected=True, reject_reason="max_positions")

    price_distance = abs(entry_price - stop_price)
    if price_distance <= 0:
        return SizingResult(0, 0, 0.0, 0.0, 0.0, rejected=True, reject_reason="zero_stop_distance")

    # Base size from fixed-fractional risk
    risk_dollars = equity * cfg.risk_per_trade
    base_qty = int(risk_dollars / price_distance)
    if base_qty <= 0:
        return SizingResult(0, 0, 0.0, 0.0, 0.0, rejected=True, reject_reason="qty_rounds_to_zero")

    multiplier = 1.5 if agreement == "consensus" else 1.0
    final_qty = int(base_qty * multiplier)

    # Notional cap: max 15% of equity per name
    max_notional = equity * cfg.max_notional_pct
    if final_qty * entry_price > max_notional:
        final_qty = int(max_notional / entry_price)

    if final_qty <= 0:
        return SizingResult(0, 0, 0.0, 0.0, 0.0, rejected=True, reject_reason="notional_cap")

    # Portfolio heat cap: keep total open risk ≤ 4% of equity
    trade_risk = final_qty * price_distance
    remaining_heat = equity * cfg.max_heat - portfolio_heat
    if remaining_heat <= 0:
        return SizingResult(0, 0, 0.0, 0.0, 0.0, rejected=True, reject_reason="heat_cap")
    if trade_risk > remaining_heat:
        final_qty = int(remaining_heat / price_distance)
        if final_qty <= 0:
            return SizingResult(0, 0, 0.0, 0.0, 0.0, rejected=True, reject_reason="heat_cap")

    notional = final_qty * entry_price
    trade_risk = final_qty * price_distance

    return SizingResult(
        base_qty=base_qty,
        final_qty=final_qty,
        agreement_multiplier=multiplier,
        notional=notional,
        risk_amount=trade_risk,
    )


@dataclass
class KillSwitchStatus:
    triggered: bool
    reason: str


def check_kill_switch(
    equity: float,
    peak_equity: float,
    daily_start_equity: float,
    cfg: Settings | None = None,
) -> KillSwitchStatus:
    """Return whether new entries should be halted.

    peak_equity      — highest equity ever recorded (from equity_curve or system_state)
    daily_start_equity — equity at the start of today's trading session
    """
    if cfg is None:
        cfg = _default_settings

    if peak_equity > 0:
        drawdown = (peak_equity - equity) / peak_equity
        if drawdown >= cfg.kill_switch_drawdown:
            return KillSwitchStatus(
                triggered=True,
                reason=f"drawdown {drawdown:.1%} ≥ {cfg.kill_switch_drawdown:.1%} from peak",
            )

    if daily_start_equity > 0:
        daily_loss = (daily_start_equity - equity) / daily_start_equity
        if daily_loss >= cfg.kill_switch_daily_loss:
            return KillSwitchStatus(
                triggered=True,
                reason=f"daily loss {daily_loss:.1%} ≥ {cfg.kill_switch_daily_loss:.1%}",
            )

    return KillSwitchStatus(triggered=False, reason="")


def portfolio_heat_from_positions(
    positions: list,  # list of BrokerPosition or Position ORM rows
    stop_map: dict[str, float],  # symbol → stop_price
) -> float:
    """Compute current portfolio heat (sum of open per-trade dollar risk)."""
    heat = 0.0
    for pos in positions:
        symbol = pos.symbol if hasattr(pos, "symbol") else pos["symbol"]
        stop = stop_map.get(symbol)
        if stop is None:
            continue
        current = (
            pos.current_price if hasattr(pos, "current_price") else pos.avg_entry_price
        )
        qty = pos.qty if hasattr(pos, "qty") else pos["qty"]
        heat += qty * max(0.0, current - stop)
    return heat
