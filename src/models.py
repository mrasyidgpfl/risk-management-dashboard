"""Domain models for risk management dashboard."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class MarketTick(BaseModel):
    """A single bid/ask price update for an instrument."""

    instrument: str
    bid: float
    ask: float
    mid: float = Field(default=0.0)
    spread: float = Field(default=0.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def model_post_init(self, __context) -> None:
        if self.mid == 0.0:
            self.mid = (self.bid + self.ask) / 2
        if self.spread == 0.0:
            self.spread = self.ask - self.bid


class Trade(BaseModel):
    """A client trade executed against our book."""

    id: str
    client: str
    instrument: str
    side: Side
    quantity: float
    price: float  # execution price (bid for sell, ask for buy)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BookPosition(BaseModel):
    """Our net position for an instrument."""

    instrument: str
    net_quantity: float = 0.0  # positive = long, negative = short
    total_pnl: float = 0.0
    unrealised_pnl: float = 0.0
    realised_pnl: float = 0.0
    monetisation: float = 0.0 
    avg_entry_price: float = 0.0
    trade_count: int = 0


class BookSnapshot(BaseModel):
    """Point-in-time snapshot of the entire book."""

    positions: dict[str, BookPosition] = Field(default_factory=dict)
    total_pnl: float = 0.0
    total_unrealised_pnl: float = 0.0
    total_realised_pnl: float = 0.0
    total_monetisation: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ClientMetrics(BaseModel):
    """Metrics for a single client's trading activity."""

    client: str
    trade_count: int = 0
    total_volume: float = 0.0
    total_spread_paid: float = 0.0  # monetisation: spread we captured
    yield_bps: float = 0.0  # client yield in basis points