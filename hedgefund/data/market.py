from datetime import date, timedelta

import pandas as pd
import structlog
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from hedgefund.config import settings
from hedgefund.data.universe import SP100

log = structlog.get_logger(__name__)

_data_client: StockHistoricalDataClient | None = None


def _client() -> StockHistoricalDataClient:
    global _data_client
    if _data_client is None:
        _data_client = StockHistoricalDataClient(
            api_key=settings.apca_api_key_id,
            secret_key=settings.apca_api_secret_key,
        )
    return _data_client


def get_bars(
    symbols: list[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    """Return a flat DataFrame with columns [symbol, timestamp, open, high, low, close, volume]."""
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    bars_set = _client().get_stock_bars(request)
    if not bars_set or not bars_set.data:
        return pd.DataFrame()

    df = bars_set.df
    if df.empty:
        return df

    # alpaca-py returns a MultiIndex (symbol, timestamp); flatten it
    df = df.reset_index()
    if "symbol" not in df.columns and df.columns[0] != "symbol":
        df = df.rename(columns={df.columns[0]: "symbol"})

    return df


def get_universe_bars(lookback_days: int = 70) -> pd.DataFrame:
    """Fetch daily bars for the full S&P 100 universe over the past `lookback_days` calendar days."""
    end = date.today()
    # Add buffer for weekends/holidays so we always get enough trading days
    start = end - timedelta(days=int(lookback_days * 1.6))
    log.info("data.fetch", symbols=len(SP100), start=str(start), end=str(end))
    return get_bars(SP100, start, end)
