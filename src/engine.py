"""Book management engine for position tracking and PnL calculation."""

from datetime import datetime

from .models import (
    BookPosition,
    BookSnapshot,
    ClientMetrics,
    MarketTick,
    Side,
    Trade,
)


class BookEngine:
    """Tracks positions, calculates PnL, and aggregates client metrics.
    
    When a client buys, we sell (go short).
    When a client sells, we buy (go long).
    """

    def __init__(self) -> None:
        self.positions: dict[str, BookPosition] = {}
        self.client_metrics: dict[str, ClientMetrics] = {}
        self.latest_ticks: dict[str, MarketTick] = {}
        self.pnl_history: list[tuple[datetime, float]] = []
        self.trades: list[Trade] = []

    def update_tick(self, tick: MarketTick) -> None:
        """Update latest market data for an instrument."""
        self.latest_ticks[tick.instrument] = tick

    def process_trade(self, trade: Trade) -> None:
        """Process a client trade and update book position.
        
        Client buys at ask -> we are short at ask price.
        Client sells at bid -> we are long at bid price.
        """
        self.trades.append(trade)
        pos = self.positions.get(
            trade.instrument,
            BookPosition(instrument=trade.instrument),
        )

        # Our side is opposite to client
        our_quantity = -trade.quantity if trade.side == Side.BUY else trade.quantity

        if pos.net_quantity == 0.0:
            # New position
            pos.avg_entry_price = trade.price
        elif (pos.net_quantity > 0 and our_quantity > 0) or (
            pos.net_quantity < 0 and our_quantity < 0
        ):
            # Adding to position — update weighted average entry
            total_qty = pos.net_quantity + our_quantity
            pos.avg_entry_price = (
                pos.avg_entry_price * pos.net_quantity
                + trade.price * our_quantity
            ) / total_qty
        else:
            # Reducing/closing/flipping position — realise PnL
            close_qty = min(abs(our_quantity), abs(pos.net_quantity))
            if pos.net_quantity > 0:
                # We were long, closing by going short
                pos.realised_pnl += close_qty * (trade.price - pos.avg_entry_price)
            else:
                # We were short, closing by going long
                pos.realised_pnl += close_qty * (pos.avg_entry_price - trade.price)

            # If flipping, set new entry price for remainder
            remainder = abs(our_quantity) - close_qty
            if remainder > 0:
                pos.avg_entry_price = trade.price

        pos.net_quantity += our_quantity
        pos.trade_count += 1
        self.positions[trade.instrument] = pos

        # Update client metrics
        self._update_client_metrics(trade)

    def _update_client_metrics(self, trade: Trade) -> None:
        """Track per-client trading metrics."""
        metrics = self.client_metrics.get(
            trade.client,
            ClientMetrics(client=trade.client),
        )
        tick = self.latest_ticks.get(trade.instrument)

        metrics.trade_count += 1
        metrics.total_volume += trade.quantity * trade.price

        if tick:
            # Spread captured = half spread per unit (we earn the spread)
            metrics.total_spread_paid += trade.quantity * tick.spread

        if metrics.total_volume > 0:
            metrics.yield_bps = (metrics.total_spread_paid / metrics.total_volume) * 10_000

        self.client_metrics[trade.client] = metrics

    def mark_to_market(self) -> None:
        """Recalculate unrealised PnL using latest market prices."""
        for instrument, pos in self.positions.items():
            tick = self.latest_ticks.get(instrument)
            if tick and pos.net_quantity != 0.0:
                if pos.net_quantity > 0:
                    # Long position: mark against bid (what we'd sell at)
                    pos.unrealised_pnl = pos.net_quantity * (
                        tick.bid - pos.avg_entry_price
                    )
                else:
                    # Short position: mark against ask (what we'd buy back at)
                    pos.unrealised_pnl = abs(pos.net_quantity) * (
                        pos.avg_entry_price - tick.ask
                    )
                pos.total_pnl = pos.realised_pnl + pos.unrealised_pnl
            self.positions[instrument] = pos

    def snapshot(self) -> BookSnapshot:
        """Create a point-in-time snapshot of the entire book."""
        self.mark_to_market()
        total_pnl = sum(p.total_pnl for p in self.positions.values())
        total_unrealised = sum(p.unrealised_pnl for p in self.positions.values())
        total_realised = sum(p.realised_pnl for p in self.positions.values())

        self.pnl_history.append((datetime.utcnow(), total_pnl))

        return BookSnapshot(
            positions=dict(self.positions),
            total_pnl=total_pnl,
            total_unrealised_pnl=total_unrealised,
            total_realised_pnl=total_realised,
        )