import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    database_url: str = "sqlite:///./dev.db"

    apca_api_key_id: str = ""
    apca_api_secret_key: str = ""

    resend_api_key: str = ""
    email_from: str = "onboarding@resend.dev"
    email_to: str = ""

    # Risk limits (ADR-0004)
    risk_per_trade: float = 0.005       # 0.5% of equity
    max_positions: int = 8
    max_notional_pct: float = 0.15      # 15% of equity per name
    max_heat: float = 0.04             # 4% total open risk
    kill_switch_drawdown: float = 0.10  # halt at -10% from peak
    kill_switch_daily_loss: float = 0.03  # pause day at -3%

    # Breakout signal parameters
    breakout_lookback: int = 20         # N-day high
    volume_multiplier: float = 1.5      # vs trailing avg
    volume_lookback: int = 50
    reward_risk: float = 2.0           # target = entry + 2*(entry-stop)
    stop_pct: float = 0.02             # stop 2% below breakout level


settings = Settings()


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
