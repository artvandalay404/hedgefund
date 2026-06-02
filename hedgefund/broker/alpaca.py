import structlog
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from hedgefund.broker.interface import AccountInfo, BrokerOrder, BrokerPosition
from hedgefund.config import settings

log = structlog.get_logger(__name__)


class AlpacaPaperAdapter:
    """Alpaca paper-trading implementation of BrokerInterface (ADR-0005)."""

    def __init__(self) -> None:
        self._client = TradingClient(
            api_key=settings.apca_api_key_id,
            secret_key=settings.apca_api_secret_key,
            paper=True,
        )

    def get_account(self) -> AccountInfo:
        acc = self._client.get_account()
        return AccountInfo(equity=float(acc.equity), cash=float(acc.cash))

    def get_positions(self) -> list[BrokerPosition]:
        positions = self._client.get_all_positions()
        return [
            BrokerPosition(
                symbol=p.symbol,
                qty=int(p.qty),
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                unrealized_pnl=float(p.unrealized_pl),
            )
            for p in positions
        ]

    def get_orders(self, status: str = "open") -> list[BrokerOrder]:
        query_status = (
            QueryOrderStatus.OPEN if status == "open" else QueryOrderStatus.ALL
        )
        orders = self._client.get_orders(
            GetOrdersRequest(status=query_status, limit=200)
        )
        return [
            BrokerOrder(
                broker_id=str(o.id),
                symbol=o.symbol,
                qty=int(o.qty),
                side=o.side.value,
                status=o.status.value,
                filled_qty=int(o.filled_qty) if o.filled_qty else 0,
                filled_avg_price=(
                    float(o.filled_avg_price) if o.filled_avg_price else None
                ),
            )
            for o in orders
        ]

    def place_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        stop_price: float,
        target_price: float,
    ) -> BrokerOrder:
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=round(stop_price, 2)),
            take_profit=TakeProfitRequest(limit_price=round(target_price, 2)),
        )
        o = self._client.submit_order(request)
        log.info("order.placed", symbol=symbol, qty=qty, broker_id=str(o.id))
        return BrokerOrder(
            broker_id=str(o.id),
            symbol=o.symbol,
            qty=int(o.qty),
            side=o.side.value,
            status=o.status.value,
        )

    def cancel_order(self, broker_order_id: str) -> None:
        self._client.cancel_order_by_id(broker_order_id)
        log.info("order.cancelled", broker_id=broker_order_id)

    def is_market_open(self) -> bool:
        return self._client.get_clock().is_open
