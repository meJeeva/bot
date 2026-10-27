"""Temporary diagnostic: drive the real controller against a stateful broker sim."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

from app.config import Settings
from app.mt5.connection import MT5Connection
from app.services.auto_trading import AutoTradingController
from tests.auto_trading_harness import FakeMonitor, VirtualClock, install_virtual_time
from tests.fakes import (
    FakeDeal,
    FakeMT5,
    FakeOrderResult,
    FakePosition,
    FakeSymbolInfo,
    FakeTick,
    broker_time,
)

MAGIC = 9001
SYMBOL = "BTCUSD.m"
ACTIONS = {1: "DEAL", 5: "PENDING", 6: "SLTP", 8: "REMOVE"}


class SimMT5(FakeMT5):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.log: list[str] = []

    def order_send(self, request):
        req = request if isinstance(request, dict) else dict(request)
        action = ACTIONS.get(req.get("action"), str(req.get("action")))
        before = [
            (o.ticket, o.type, o.price, o.sl) for o in self.orders
        ]
        pos_before = [(p.ticket, p.sl) for p in self.positions]
        result = super().order_send(request)
        after = [(o.ticket, o.type, o.price, o.sl) for o in self.orders]
        pos_after = [(p.ticket, p.sl) for p in self.positions]
        self.log.append(
            f"{action:8s} type={req.get('type')} price={req.get('price')} sl={req.get('sl')} "
            f"order={req.get('order')} position={req.get('position')} "
            f"orders {before}->{after} positions {pos_before}->{pos_after}"
        )
        return result

    def tick(self, bid, ask):
        """Broker-side processing of a new quote."""
        for order in list(self.orders):
            filled = (order.type == 4 and ask >= order.price) or (
                order.type == 5 and bid <= order.price
            )
            if not filled:
                continue
            self.orders.remove(order)
            self.positions.append(
                FakePosition(
                    ticket=self.next_position_ticket,
                    type=0 if order.type == 4 else 1,
                    magic=order.magic,
                    volume=order.volume,
                    price_open=order.price,
                    price_current=order.price,
                    sl=order.sl,
                    symbol=order.symbol,
                )
            )
            self.next_position_ticket += 1
            self.log.append(f"BROKER  filled order {order.ticket} @ {order.price} sl={order.sl}")
        for pos in list(self.positions):
            hit = (pos.type == 0 and bid <= pos.sl) or (pos.type == 1 and ask >= pos.sl)
            if not hit or not pos.sl:
                continue
            self.positions.remove(pos)
            self.deals.append(
                FakeDeal(
                    ticket=9999,
                    position_id=pos.ticket,
                    position=pos.ticket,
                    price=pos.sl,
                    profit=0.0,
                    symbol=pos.symbol,
                    comment="sl",
                    reason=4,
                    entry=1,
                )
            )
            self.log.append(f"BROKER  SL hit position {pos.ticket} @ {pos.sl}")


def btc_fake(stops_level: int = 0) -> SimMT5:
    info = FakeSymbolInfo(
        SYMBOL,
        digits=2,
        point=0.01,
        trade_tick_size=0.01,
        currency_base="BTC",
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
        spread=1200,
        trade_stops_level=stops_level,
        trade_freeze_level=0,
    )
    fake = SimMT5(
        symbols=[info],
        ticks={SYMBOL: FakeTick(time=broker_time(), bid=104_000.0, ask=104_012.0)},
    )
    return fake


BTC_SETTINGS = dict(
    mt5_symbol="BTCUSD",
    mt5_symbol_candidates="BTCUSD,BTCUSDm,BTCUSD.,BTCUSD.m",
    auto_trade_entry_offset=15.0,
    auto_trade_break_even_offset=4.0,
    auto_trade_trailing_distance=4.0,
    auto_trade_lot_size=1.0,
    auto_trade_max_spread_points=2000.0,
    database_enabled=False,
    log_level="WARNING",
)


async def main():
    from tests import auto_trading_harness as harness

    clock = VirtualClock()

    class Patched(harness.VirtualClock):
        pass

    # monkeypatch-free install of virtual time
    AutoTradingController._now = lambda self: clock.now()

    async def _sleep(self, seconds):
        clock.advance(seconds)
        await asyncio.sleep(0)

    AutoTradingController._sleep = _sleep

    fake = btc_fake()
    settings = Settings(_env_file=None, **BTC_SETTINGS)
    connection = MT5Connection(settings, mt5_module=fake)
    await connection.initialize()
    monitor = FakeMonitor(symbol=SYMBOL, spread_points=1200.0)
    monitor.quote = SimpleNamespace(bid=104_000.0, ask=104_012.0, spread_points=1200.0, is_stale=False)
    controller = AutoTradingController(settings, connection, monitor)

    await controller.start()
    print("status", controller._status, controller._phase, controller._last_error)

    async def step(bid, ask, label):
        monitor.quote = SimpleNamespace(
            bid=bid, ask=ask, spread_points=(ask - bid) / 0.01, is_stale=False
        )
        fake.tick(bid, ask)
        clock.advance(0.2)
        await asyncio.sleep(0.01)
        print(f"--- {label} bid={bid} ask={ask} phase={controller._phase} pos={controller._position_ticket} "
              f"coll={controller._current_sl} tickets=({controller._buy_order_ticket},{controller._sell_order_ticket}) "
              f"err={controller._last_error} failed={controller._failed_entries} "
              f"retry={controller._order_retry_at}")

    # flat market
    for _ in range(10):
        await step(104_000.0, 104_012.0, "flat")

    mark = len(fake.log)
    # ticks that oscillate around the reference, still below entry
    for i in range(40):
        await step(104_000.0 + (i % 5), 104_012.0 + (i % 5), "osc")

    print("\n=== order_send calls after flat+oscillation ===")
    for line in fake.log[mark:][:60]:
        print(line)
    print("total order_send:", len(fake.log))

    # --- fill the buy stop -------------------------------------------
    mark = len(fake.log)
    for i in range(20):
        bid = 104_021.0 + i
        await step(bid, bid + 12.0, "rise")
    print("\n=== after the buy stop filled ===")
    for line in fake.log[mark:]:
        print(line)
    print("phase", controller._phase, "pos", controller._position_ticket, "sl", controller._current_sl,
          "be", controller._break_even_active, controller._break_even_level)

    # --- let price hover just above activation -----------------------
    mark = len(fake.log)
    base = (controller._entry_price or 104_021.0) + 5.0
    for i in range(60):
        bid = base + (i % 6)
        await step(bid, bid + 12.0, "hover")
    print("\n=== while hovering above activation ===")
    for line in fake.log[mark:]:
        print(line)
    print("phase", controller._phase, "pos", controller._position_ticket, "sl", controller._current_sl,
          "be", controller._break_even_active, controller._break_even_level)
    await controller.stop()


asyncio.run(main())
