"""Application configuration with scalability controls."""

from pydantic import BaseModel


class AppConfig(BaseModel):
    """Central configuration for tuning scale and performance."""

    # Market data
    tick_interval_ms: int = 100  # ms between price ticks

    # Trade simulation
    trade_interval_ms: int = 500
    trade_probability: float = 0.3

    # Dashboard
    ws_throttle_ms: int = 250  # minimum ms between WebSocket pushes
    pnl_history_max: int = 500  # max points on PnL chart

    # Server
    host: str = "0.0.0.0"
    port: int = 8080