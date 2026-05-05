"""Quart application with WebSocket streaming and dashboard."""

import asyncio
import json
import time

from quart import (
    Quart,
    abort,
    jsonify,
    render_template,
    request,
    websocket,
)

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


# ---------- Background workers ----------

async def process_ticks(tick_queue: asyncio.Queue) -> None:
    """Process market ticks and update engine."""
    while True:
        tick: MarketTick = await tick_queue.get()
        engine.update_tick(tick)


async def process_trades(trade_queue: asyncio.Queue) -> None:
    """Process trades and update engine. Broadcasting is handled by broadcast_loop."""
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
        "total_monetisation": snapshot.total_monetisation,
        "pnl_per_client": {k: round(v, 2) for k, v in engine.pnl_per_client.items()},
        "positions": {
            k: {
                "instrument": v.instrument,
                "net_quantity": v.net_quantity,
                "total_pnl": v.total_pnl,
                "unrealised_pnl": v.unrealised_pnl,
                "realised_pnl": v.realised_pnl,
                "monetisation": v.monetisation,
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


# ---------- CLI / API endpoints ----------
# Read-only views into engine state for traders who need sub-throttle latency
# (the WS pushes are throttled to ~ws_throttle_ms; these are point-in-time reads).
# Safe without locking: Quart runs everything on a single event loop, so handlers
# can't be interrupted mid-snapshot by the tick/trade processors.

def _summary_dict() -> dict:
    snap = engine.snapshot()
    trade_count = sum(p.trade_count for p in snap.positions.values())
    return {
        "timestamp": snap.timestamp.isoformat(),
        "total_pnl": round(snap.total_pnl, 2),
        "total_unrealised_pnl": round(snap.total_unrealised_pnl, 2),
        "total_realised_pnl": round(snap.total_realised_pnl, 2),
        "total_monetisation": round(snap.total_monetisation, 2),
        "total_trades": trade_count,
        "instruments": len(snap.positions),
    }


def _tick_dict(t) -> dict:
    return {
        "instrument": t.instrument,
        "bid": t.bid,
        "ask": t.ask,
        "mid": round((t.bid + t.ask) / 2, 5),
        "spread": round(t.spread, 5),
    }


def _position_dict(p) -> dict:
    return {
        "instrument": p.instrument,
        "net_quantity": p.net_quantity,
        "total_pnl": round(p.total_pnl, 2),
        "unrealised_pnl": round(p.unrealised_pnl, 2),
        "realised_pnl": round(p.realised_pnl, 2),
        "monetisation": round(p.monetisation, 2),
        "trade_count": p.trade_count,
    }


def _client_dicts() -> list[dict]:
    rows = []
    for k, v in engine.client_metrics.items():
        rows.append({
            "client": v.client,
            "trade_count": v.trade_count,
            "total_volume": round(v.total_volume, 2),
            "total_spread_paid": round(v.total_spread_paid, 4),
            "yield_bps": round(v.yield_bps, 2),
            "realised_pnl": round(engine.pnl_per_client.get(k, 0.0), 2),
        })
    rows.sort(key=lambda r: r["total_volume"], reverse=True)
    return rows


def _format_table(rows: list[dict]) -> str:
    """Minimal ASCII table — no deps, curl-friendly."""
    if not rows:
        return "(no rows)\n"
    cols = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    sep = "  "
    lines = [sep.join(c.ljust(widths[c]) for c in cols)]
    lines.append(sep.join("-" * widths[c] for c in cols))
    for r in rows:
        lines.append(sep.join(str(r[c]).ljust(widths[c]) for c in cols))
    return "\n".join(lines) + "\n"


def _respond(payload):
    """JSON by default; ?format=table renders rows as ASCII."""
    if request.args.get("format") == "table":
        rows = payload if isinstance(payload, list) else [payload]
        return _format_table(rows), 200, {"Content-Type": "text/plain; charset=utf-8"}
    return jsonify(payload)


@app.route("/api/summary")
async def api_summary():
    return _respond(_summary_dict())


@app.route("/api/ticks")
async def api_ticks():
    return _respond([_tick_dict(t) for t in engine.latest_ticks.values()])


@app.route("/api/ticks/<instrument>")
async def api_tick_one(instrument: str):
    t = engine.latest_ticks.get(instrument.upper())
    if t is None:
        abort(404, description=f"unknown instrument: {instrument}")
    return _respond(_tick_dict(t))


@app.route("/api/positions")
async def api_positions():
    snap = engine.snapshot()
    return _respond([_position_dict(p) for p in snap.positions.values()])


@app.route("/api/positions/<instrument>")
async def api_position_one(instrument: str):
    snap = engine.snapshot()
    p = snap.positions.get(instrument.upper())
    if p is None:
        abort(404, description=f"unknown instrument: {instrument}")
    return _respond(_position_dict(p))


@app.route("/api/clients")
async def api_clients():
    return _respond(_client_dicts())


# ---------- App lifecycle ----------

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