"""Transaction cost model for the backtester.

S&P 100 mega-caps are extremely liquid; costs are small but non-zero.
These defaults are conservative estimates for a price-taker using market orders.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostModel:
    half_spread_pct: float = 0.0005   # 5 bps per side (realistic for mega-caps)
    slippage_pct: float = 0.0002      # 2 bps market impact

    def fill_price(self, nominal: float, side: str) -> float:
        """Return simulated fill price after spread and slippage."""
        adj = self.half_spread_pct + self.slippage_pct
        return nominal * (1 + adj) if side == "buy" else nominal * (1 - adj)
