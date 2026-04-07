"""Quart application with WebSocket streaming and dashboard."""

import asyncio
import json
import time

from quart import Quart, render_template, websocket

from .config import AppConfig
from .engine import BookEngine
from .models import MarketTick, Trade
from .streamer import MarketDataStreamer
from .simulator import TradeSimulator

app = Quart(__name__, template_folder="templates")

config = AppConfig()
engine = BookEngine()
streamer = MarketDataStreamer(tick_interval=config.tick_interval_ms / 1000)
simulator: TradeSimulator | None = None
ws_clients: set = set()
_last_broadcast: float = 0.0


async def process_ticks(tick_queue: asyncio.Queue) -> None:
    """Process market ticks and update engine."""
    while True:
        tick: MarketTick = await tick_queue.get()
        engine.update_tick(tick)


async def process_trades(trade_queue: asyncio.Queue) -> None:
    """Process trades, update engine, and push snapshots to WebSocket clients."""
    while True:
        trade: Trade = await trade_queue.get()
        engine.process_trade(trade)
        await maybe_broadcast()


async def maybe_broadcast() -> None:
    """Throttled broadcast — skips if too soon since last push."""
    global _last_broadcast
    now = time.monotonic()
    if (now - _last_broadcast) < (config.ws_throttle_ms / 1000):
        return
    _last_broadcast = now
    await broadcast_snapshot()


async def broadcast_snapshot() -> None:
    """Send current book snapshot to all connected WebSocket clients."""
    global ws_clients
    snapshot = engine.snapshot()

    # Trim PnL history
    if len(engine.pnl_history) > config.pnl_history_max:
        engine.pnl_history = engine.pnl_history[-config.pnl_history_max:]

    data = {
        "type": "snapshot",
        "timestamp": snapshot.timestamp.isoformat(),
        "total_pnl": snapshot.total_pnl,
        "total_unrealised_pnl": snapshot.total_unrealised_pnl,
        "total_realised_pnl": snapshot.total_realised_pnl,
        "positions": {
            k: {
                "instrument": v.instrument,
                "net_quantity": v.net_quantity,
                "total_pnl": v.total_pnl,
                "unrealised_pnl": v.unrealised_pnl,
                "realised_pnl": v.realised_pnl,
                "trade_count": v.trade_count,
            }
            for k, v in snapshot.positions.items()
        },
        "pnl_history": [
            {"time": t.isoformat(), "pnl": p} for t, p in engine.pnl_history[-200:]
        ],
        "client_metrics": {
            k: {
                "client": v.client,
                "trade_count": v.trade_count,
                "total_volume": round(v.total_volume, 2),
                "total_spread_paid": round(v.total_spread_paid, 4),
                "yield_bps": round(v.yield_bps, 2),
            }
            for k, v in engine.client_metrics.items()
        },
        "latest_ticks": {
            k: {
                "instrument": v.instrument,
                "bid": v.bid,
                "ask": v.ask,
                "spread": round(v.spread, 5),
            }
            for k, v in engine.latest_ticks.items()
        },
    }

    payload = json.dumps(data)
    disconnected = set()
    for client in ws_clients:
        try:
            await client.send(payload)
        except Exception:
            disconnected.add(client)
    ws_clients -= disconnected


@app.before_serving
async def startup() -> None:
    """Start background tasks."""
    global simulator

    tick_queue_engine = streamer.subscribe()
    tick_queue_simulator = streamer.subscribe()
    simulator = TradeSimulator(
        tick_queue=tick_queue_simulator,
        trade_interval=config.trade_interval_ms / 1000,
        trade_probability=config.trade_probability,
    )
    trade_queue = simulator.subscribe()

    app.add_background_task(streamer.start)
    app.add_background_task(simulator.start)
    app.add_background_task(process_ticks, tick_queue_engine)
    app.add_background_task(process_trades, trade_queue)


@app.route("/")
async def index():
    return await render_template("dashboard.html")


@app.websocket("/ws")
async def ws():
    ws_clients.add(websocket._get_current_object())
    try:
        while True:
            await websocket.receive()
    except asyncio.CancelledError:
        pass
    finally:
        ws_clients.discard(websocket._get_current_object())


def main() -> None:
    app.run(host=config.host, port=config.port)


if __name__ == "__main__":
    main()