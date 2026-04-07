# Risk Management Dashboard

MVP risk management dashboard visualising real-time book management metrics. Simulates a market-making environment where clients trade against our prices and exposure accumulates on our book.

## Quick Start

```bash
git clone https://github.com/mrasyidgpfl/risk-management-dashboard.git
cd risk-management-dashboard
uv sync
uv run python -m src.app
```

Open [http://localhost:8080](http://localhost:8080).

### Docker (alternative)

```bash
docker compose up --build
```

## Tests

```bash
uv run pytest tests/ -v
```

## Architecture

The application runs as a single async process with four concurrent components:

```
Market Data Streamer ──→ Book Engine ──→ WebSocket ──→ Dashboard
                              ↑
Trade Simulator ──────────────┘
```

- **Market Data Streamer** — generates random-walk bid/ask prices for 5 FX instruments at configurable intervals. Publishes ticks to subscribers via async queues.
- **Trade Simulator** — consumes price ticks and simulates client trading activity. Clients randomly buy (at ask) or sell (at bid), creating positions on our book.
- **Book Engine** — core business logic. Tracks net positions per instrument, calculates realised and unrealised PnL (mark-to-market), and aggregates client metrics (volume, spread captured, yield).
- **Dashboard** — Quart web app serving a Plotly.js frontend. Receives real-time updates via WebSocket with configurable throttling.

## Book Logic

- Client **buys** at our ask price → we go **short**
- Client **sells** at our bid price → we go **long**
- Unrealised PnL is marked to market against the current bid (for longs) or ask (for shorts)
- Realised PnL is locked in when positions are reduced or closed

## Dashboard Metrics

| Metric | Description |
|--------|-------------|
| Total PnL | Realised + unrealised PnL across all instruments |
| PnL Curve | Time series of total book PnL |
| Net Exposure | Current long/short position per instrument |
| PnL Attribution | PnL breakdown by instrument |
| Client Metrics | Per-client trade count, volume, spread captured, and yield in basis points |
| Live Prices | Real-time bid/ask/spread for all instruments |

## Configuration

All parameters are tuneable in `src/config.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `tick_interval_ms` | 100 | Milliseconds between price ticks |
| `trade_interval_ms` | 500 | Milliseconds between trade attempts |
| `trade_probability` | 0.3 | Probability a trade occurs each interval |
| `ws_throttle_ms` | 250 | Minimum ms between WebSocket pushes |
| `pnl_history_max` | 500 | Max data points retained on PnL chart |

See [docs/SCALING.md](docs/SCALING.md) for scalability analysis.

## Tech Stack

- **Python 3.10+** with **asyncio** for concurrency
- **Quart** — async web framework (async Flask)
- **Pydantic** — data validation and modelling
- **Plotly.js** — interactive charts with hover tooltips
- **WebSockets** — real-time data streaming to frontend
- **uv** — dependency management and reproducible environments
- **pytest** — testing

## Project Structure

```
src/
├── models.py        # Pydantic domain models
├── engine.py        # Book management and PnL engine
├── streamer.py      # Mock market data generator
├── simulator.py     # Mock client trade simulator
├── config.py        # Centralised configuration
├── app.py           # Quart app, WebSocket, routes
└── templates/
    └── dashboard.html
tests/
└── test_engine.py
docs/
├── SCALING.md
└── AI_USAGE.md
```

## Production Extensions

In a production environment, this architecture naturally extends to:

- **Celery + Redis** for scheduled report generation and periodic PnL snapshots
- **PostgreSQL** for trade persistence and historical analysis
- **gRPC / message queues** for real pricing feed integration
- **Hypercorn** as an ASGI production server behind a reverse proxy
