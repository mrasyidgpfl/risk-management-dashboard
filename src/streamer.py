"""Mock market data streamer generating random-walk bid/ask prices."""

import asyncio
import random
from datetime import datetime

from .models import MarketTick

# Mock instruments with starting mid prices
INSTRUMENTS = {
    "EUR/USD": 1.1000,
    "GBP/USD": 1.2700,
    "USD/JPY": 155.00,
    "AUD/USD": 0.6500,
    "USD/CHF": 0.9100,
    "SPXUSD": 5800.00,     # US Large Cap 500
    "D30EUR": 18500.00,    # Germany 40 Index
}

# Typical spread in price units per instrument
SPREADS = {
    "EUR/USD": 0.0002,
    "GBP/USD": 0.0003,
    "USD/JPY": 0.02,
    "AUD/USD": 0.0002,
    "USD/CHF": 0.0003,
    "SPXUSD": 0.50,
    "D30EUR": 1.50,
}

class MarketDataStreamer:
    """Generates mock bid/ask prices using a random walk."""

    def __init__(self, instruments: dict[str, float] | None = None, tick_interval: float = 0.1) -> None:
        self.prices = dict(instruments or INSTRUMENTS)
        self.tick_interval = tick_interval
        self.subscribers: list[asyncio.Queue] = []
        self._running = False

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to market data updates."""
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(queue)
        return queue

    async def start(self) -> None:
        """Start streaming price ticks."""
        self._running = True
        while self._running:
            for instrument, mid in self.prices.items():
                # Random walk: small percentage move
                change = random.gauss(0, 0.0001) * mid
                new_mid = mid + change
                self.prices[instrument] = new_mid

                half_spread = SPREADS.get(instrument, 0.0002) / 2
                tick = MarketTick(
                    instrument=instrument,
                    bid=round(new_mid - half_spread, 5),
                    ask=round(new_mid + half_spread, 5),
                    timestamp=datetime.utcnow(),
                )

                for queue in self.subscribers:
                    await queue.put(tick)

            await asyncio.sleep(self.tick_interval)

    def stop(self) -> None:
        self._running = False