# Scalability

## Current Throughput

At default settings:

- ~50 ticks/second (5 instruments × 100ms interval)
- ~15 trades/second (5 clients, 500ms interval, 30% probability)
- 4 WebSocket pushes/second (250ms throttle)

## 10x Scale

50 instruments, 50 clients → ~500 ticks/second, ~150 trades/second.

**No issues:** asyncio queues and the book engine (O(1) dict lookups per trade) handle this comfortably. Pydantic serialisation cost scales linearly with number of positions but remains negligible.

**Bottleneck:** the browser. Plotly.js re-rendering multiple charts 4 times/second with larger datasets causes frame drops before the backend struggles. Mitigation: increase `ws_throttle_ms` from 250 to 500-1000.

## Throttling

`ws_throttle_ms` in `src/config.py` controls the minimum interval between dashboard updates. The backend processes every tick and trade regardless — throttling only reduces how often snapshots are pushed to the frontend. No data is lost.

## Beyond Single Process

At significantly higher scale, the in-memory queues swap out for external message brokers (Redis, Kafka) and the components run as separate services. The current async queue abstraction makes this a straightforward migration.
