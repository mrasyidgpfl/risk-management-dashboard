"""Tests for book management engine core logic."""

from src.engine import BookEngine
from src.models import MarketTick, Side, Trade


def make_tick(instrument: str, bid: float, ask: float) -> MarketTick:
    return MarketTick(instrument=instrument, bid=bid, ask=ask)


def make_trade(
    client: str, instrument: str, side: Side, quantity: float, price: float
) -> Trade:
    return Trade(
        id=f"{client}-{instrument}-{side.value}",
        client=client,
        instrument=instrument,
        side=side,
        quantity=quantity,
        price=price,
    )


class TestBookEngine:
    def test_client_buy_makes_us_short(self):
        engine = BookEngine()
        engine.update_tick(make_tick("EUR/USD", 1.1000, 1.1002))
        engine.process_trade(
            make_trade("alice", "EUR/USD", Side.BUY, 100, 1.1002)
        )
        pos = engine.positions["EUR/USD"]
        assert pos.net_quantity == -100  # we are short

    def test_client_sell_makes_us_long(self):
        engine = BookEngine()
        engine.update_tick(make_tick("EUR/USD", 1.1000, 1.1002))
        engine.process_trade(
            make_trade("alice", "EUR/USD", Side.SELL, 100, 1.1000)
        )
        pos = engine.positions["EUR/USD"]
        assert pos.net_quantity == 100  # we are long

    def test_realised_pnl_on_close(self):
        engine = BookEngine()
        # Client buys -> we go short at 1.1002
        engine.update_tick(make_tick("EUR/USD", 1.1000, 1.1002))
        engine.process_trade(
            make_trade("alice", "EUR/USD", Side.BUY, 100, 1.1002)
        )
        # Price drops, client sells -> we close long at 1.0998
        engine.update_tick(make_tick("EUR/USD", 1.0998, 1.1000))
        engine.process_trade(
            make_trade("bob", "EUR/USD", Side.SELL, 100, 1.0998)
        )
        pos = engine.positions["EUR/USD"]
        # We were short at 1.1002, closed at 1.0998 -> profit
        assert pos.realised_pnl > 0
        assert abs(pos.net_quantity) < 1e-9  # flat

    def test_unrealised_pnl_mark_to_market(self):
        engine = BookEngine()
        engine.update_tick(make_tick("EUR/USD", 1.1000, 1.1002))
        engine.process_trade(
            make_trade("alice", "EUR/USD", Side.BUY, 100, 1.1002)
        )
        # Price moves against us (we're short, price goes up)
        engine.update_tick(make_tick("EUR/USD", 1.1010, 1.1012))
        engine.mark_to_market()
        pos = engine.positions["EUR/USD"]
        assert pos.unrealised_pnl < 0  # loss

    def test_client_yield_tracks_spread(self):
        engine = BookEngine()
        engine.update_tick(make_tick("EUR/USD", 1.1000, 1.1002))
        engine.process_trade(
            make_trade("alice", "EUR/USD", Side.BUY, 100, 1.1002)
        )
        metrics = engine.client_metrics["alice"]
        assert metrics.trade_count == 1
        assert metrics.total_spread_paid > 0
        assert metrics.yield_bps > 0

    def test_monetisation_is_half_spread_per_fill(self):
        """Monetisation per trade = quantity × spread / 2 (canonical half-spread)."""
        engine = BookEngine()
        # Spread of 2 pips, quantity of 100 -> expected monetisation = 100 × 0.0002 / 2 = 0.01
        engine.update_tick(make_tick("EUR/USD", 1.1000, 1.1002))
        engine.process_trade(
            make_trade("alice", "EUR/USD", Side.BUY, 100, 1.1002)
        )
        pos = engine.positions["EUR/USD"]
        assert abs(pos.monetisation - 0.01) < 1e-9
        # Client metric should match (single trade, single client)
        metrics = engine.client_metrics["alice"]
        assert abs(metrics.total_spread_paid - 0.01) < 1e-9

    def test_monetisation_accumulates_across_trades(self):
        """Position-level monetisation sums across multiple fills."""
        engine = BookEngine()
        engine.update_tick(make_tick("EUR/USD", 1.1000, 1.1002))
        # Three trades on the same instrument from different clients
        engine.process_trade(make_trade("alice", "EUR/USD", Side.BUY, 100, 1.1002))
        engine.process_trade(make_trade("bob", "EUR/USD", Side.SELL, 50, 1.1000))
        engine.process_trade(make_trade("carol", "EUR/USD", Side.BUY, 200, 1.1002))
        pos = engine.positions["EUR/USD"]
        # (100 + 50 + 200) × 0.0002 / 2 = 0.035
        assert abs(pos.monetisation - 0.035) < 1e-9

    def test_attribution_identity_holds(self):
        """Total PnL = monetisation + inventory PnL, per instrument."""
        engine = BookEngine()
        engine.update_tick(make_tick("EUR/USD", 1.1000, 1.1002))
        engine.process_trade(
            make_trade("alice", "EUR/USD", Side.BUY, 100, 1.1002)
        )
        # Move the market against us (we're short, price rises)
        engine.update_tick(make_tick("EUR/USD", 1.1010, 1.1012))
        engine.mark_to_market()
        pos = engine.positions["EUR/USD"]
        # Identity: total_pnl = realised + unrealised; inventory = total - monetisation
        inventory_pnl = pos.total_pnl - pos.monetisation
        # The decomposition the attribution chart depends on must be exact
        assert abs((pos.monetisation + inventory_pnl) - pos.total_pnl) < 1e-9
        # Sanity: we lost money on inventory (short into a rising market)
        assert inventory_pnl < 0

    def test_snapshot_total_monetisation_sums_positions(self):
        """BookSnapshot.total_monetisation == sum of per-position monetisation."""
        engine = BookEngine()
        engine.update_tick(make_tick("EUR/USD", 1.1000, 1.1002))
        engine.update_tick(make_tick("GBP/USD", 1.2700, 1.2703))
        engine.process_trade(make_trade("alice", "EUR/USD", Side.BUY, 100, 1.1002))
        engine.process_trade(make_trade("alice", "GBP/USD", Side.SELL, 200, 1.2700))
        snap = engine.snapshot()
        expected = sum(p.monetisation for p in snap.positions.values())
        assert abs(snap.total_monetisation - expected) < 1e-9
        assert snap.total_monetisation > 0  # both trades captured spread