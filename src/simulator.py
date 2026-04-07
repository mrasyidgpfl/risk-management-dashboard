"""Mock trade simulator generating client trading activity."""

import asyncio
import random
import uuid
from datetime import datetime

from .models import MarketTick, Side, Trade

CLIENTS = ["alpha_capital", "summit_trading", "horizon_fund", "vertex_markets", "peak_invest"]


class TradeSimulator:
    """Simulates clients trading against our prices."""

    def __init__(
        self,
        tick_queue: asyncio.Queue,
        trade_interval: float = 0.5,
        trade_probability: float = 0.3,
    ) -> None:
        self.tick_queue = tick_queue
        self.trade_interval = trade_interval
        self.trade_probability = trade_probability
        self.latest_ticks: dict[str, MarketTick] = {}
        self.subscribers: list[asyncio.Queue] = []
        self._running = False

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to trade updates."""
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(queue)
        return queue

    async def _consume_ticks(self) -> None:
        """Keep latest tick per instrument up to date."""
        while self._running:
            try:
                tick = await asyncio.wait_for(self.tick_queue.get(), timeout=1.0)
                self.latest_ticks[tick.instrument] = tick
            except asyncio.TimeoutError:
                continue

    async def start(self) -> None:
        """Start simulating trades."""
        self._running = True
        asyncio.create_task(self._consume_ticks())

        while self._running:
            if self.latest_ticks and random.random() < self.trade_probability:
                instrument = random.choice(list(self.latest_ticks.keys()))
                tick = self.latest_ticks[instrument]
                side = random.choice([Side.BUY, Side.SELL])
                quantity = random.choice([10, 25, 50, 100, 250, 500])

                trade = Trade(
                    id=str(uuid.uuid4())[:8],
                    client=random.choice(CLIENTS),
                    instrument=instrument,
                    side=side,
                    quantity=quantity,
                    price=tick.ask if side == Side.BUY else tick.bid,
                    timestamp=datetime.utcnow(),
                )

                for queue in self.subscribers:
                    await queue.put(trade)

            await asyncio.sleep(self.trade_interval)

    def stop(self) -> None:
        self._running = False