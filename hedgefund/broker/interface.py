from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class AccountInfo:
    equity: float
    cash: float


@dataclass
class BrokerPosition:
    symbol: str
    qty: int
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float


@dataclass
class BrokerOrder:
    broker_id: str
    symbol: str
    qty: int
    side: str           # buy | sell
    status: str         # pending_new | new | filled | canceled | ...
    filled_qty: int = 0
    filled_avg_price: float | None = None


@runtime_checkable
class BrokerInterface(Protocol):
    def get_account(self) -> AccountInfo: ...
    def get_positions(self) -> list[BrokerPosition]: ...
    def get_orders(self, status: str = "open") -> list[BrokerOrder]: ...
    def place_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        stop_price: float,
        target_price: float,
    ) -> BrokerOrder: ...
    def cancel_order(self, broker_order_id: str) -> None: ...
    def is_market_open(self) -> bool: ...
