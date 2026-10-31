import pytest
from types import SimpleNamespace
from app.config import Settings
from app.mt5.connection import MT5Connection
from app.services.auto_trading import AutoTradingController
from tests.fakes import FakeMT5, FakeAccountInfo, gold_terminal_with_live_tick

def make_settings(**overrides):
    overrides.setdefault("database_enabled", False)
    overrides.setdefault("auto_trade_demo_only", True)
    overrides.setdefault("auto_trade_demo_authorized", True)
    overrides.setdefault("live_trading_enabled", False)
    return Settings(_env_file=None, **overrides)

def make_controller(fake, **overrides):
    settings = make_settings(**overrides)
    conn = MT5Connection(settings, mt5_module=fake)
    # initialize synchronously not needed; _demo_account_authorized calls is_connected via acall
    # ensure initialized
    import asyncio
    asyncio.get_event_loop().run_until_complete(conn.initialize()) if False else None
    monitor = SimpleNamespace(symbol_status=SimpleNamespace(requested="XAUUSD", resolved="XAUUSD", resolution="resolved"), latest_quote=lambda: SimpleNamespace(bid=1, ask=2, spread_points=1, is_stale=False))
    return AutoTradingController(settings, conn, monitor), conn, settings

@pytest.mark.asyncio
async def test_authorized_demo():
    fake = gold_terminal_with_live_tick()
    fake.account = FakeAccountInfo(trade_mode=0, trade_allowed=True, trade_expert=True)
    fake.initialize() if hasattr(fake, "initialize") else None
    # initialize MT5
    await None if False else None
    settings = make_settings()
    conn = MT5Connection(settings, mt5_module=fake)
    await conn.initialize()
    c = AutoTradingController(settings, conn, SimpleNamespace(symbol_status=SimpleNamespace(requested="XAUUSD", resolved="XAUUSD", resolution="resolved"), latest_quote=lambda: SimpleNamespace(bid=1, ask=2, spread_points=1, is_stale=False)))
    assert await c._demo_account_authorized() is True

@pytest.mark.asyncio
async def test_unauthorized_demo():
    fake = gold_terminal_with_live_tick()
    fake.account = FakeAccountInfo(trade_mode=0, trade_allowed=True, trade_expert=True)
    settings = make_settings(auto_trade_demo_authorized=False)
    conn = MT5Connection(settings, mt5_module=fake)
    await conn.initialize()
    c = AutoTradingController(settings, conn, SimpleNamespace(symbol_status=SimpleNamespace(requested="XAUUSD", resolved="XAUUSD", resolution="resolved"), latest_quote=lambda: SimpleNamespace(bid=1, ask=2, spread_points=1, is_stale=False)))
    assert await c._demo_account_authorized() is False

@pytest.mark.asyncio
async def test_real_account_rejected():
    fake = gold_terminal_with_live_tick()
    fake.account = FakeAccountInfo(trade_mode=2, trade_allowed=True, trade_expert=True)
    settings = make_settings()
    conn = MT5Connection(settings, mt5_module=fake)
    await conn.initialize()
    c = AutoTradingController(settings, conn, SimpleNamespace(symbol_status=SimpleNamespace(requested="XAUUSD", resolved="XAUUSD", resolution="resolved"), latest_quote=lambda: SimpleNamespace(bid=1, ask=2, spread_points=1, is_stale=False)))
    assert await c._demo_account_authorized() is False

@pytest.mark.asyncio
async def test_contest_account_rejected():
    fake = gold_terminal_with_live_tick()
    fake.account = FakeAccountInfo(trade_mode=1, trade_allowed=True, trade_expert=True)
    settings = make_settings()
    conn = MT5Connection(settings, mt5_module=fake)
    await conn.initialize()
    c = AutoTradingController(settings, conn, SimpleNamespace(symbol_status=SimpleNamespace(requested="XAUUSD", resolved="XAUUSD", resolution="resolved"), latest_quote=lambda: SimpleNamespace(bid=1, ask=2, spread_points=1, is_stale=False)))
    assert await c._demo_account_authorized() is False

@pytest.mark.asyncio
async def test_unknown_trade_mode():
    fake = gold_terminal_with_live_tick()
    fake.account = FakeAccountInfo(trade_mode=99, trade_allowed=True, trade_expert=True)
    settings = make_settings()
    conn = MT5Connection(settings, mt5_module=fake)
    await conn.initialize()
    c = AutoTradingController(settings, conn, SimpleNamespace(symbol_status=SimpleNamespace(requested="XAUUSD", resolved="XAUUSD", resolution="resolved"), latest_quote=lambda: SimpleNamespace(bid=1, ask=2, spread_points=1, is_stale=False)))
    assert await c._demo_account_authorized() is False

@pytest.mark.asyncio
async def test_account_info_none():
    fake = gold_terminal_with_live_tick()
    fake.account = None
    settings = make_settings()
    conn = MT5Connection(settings, mt5_module=fake)
    await conn.initialize()
    c = AutoTradingController(settings, conn, SimpleNamespace(symbol_status=SimpleNamespace(requested="XAUUSD", resolved="XAUUSD", resolution="resolved"), latest_quote=lambda: SimpleNamespace(bid=1, ask=2, spread_points=1, is_stale=False)))
    assert await c._demo_account_authorized() is False

@pytest.mark.asyncio
async def test_trade_allowed_false():
    fake = gold_terminal_with_live_tick()
    fake.account = FakeAccountInfo(trade_mode=0, trade_allowed=False, trade_expert=True)
    settings = make_settings()
    conn = MT5Connection(settings, mt5_module=fake)
    await conn.initialize()
    c = AutoTradingController(settings, conn, SimpleNamespace(symbol_status=SimpleNamespace(requested="XAUUSD", resolved="XAUUSD", resolution="resolved"), latest_quote=lambda: SimpleNamespace(bid=1, ask=2, spread_points=1, is_stale=False)))
    assert await c._demo_account_authorized() is False

@pytest.mark.asyncio
async def test_trade_expert_false():
    fake = gold_terminal_with_live_tick()
    fake.account = FakeAccountInfo(trade_mode=0, trade_allowed=True, trade_expert=False)
    settings = make_settings()
    conn = MT5Connection(settings, mt5_module=fake)
    await conn.initialize()
    c = AutoTradingController(settings, conn, SimpleNamespace(symbol_status=SimpleNamespace(requested="XAUUSD", resolved="XAUUSD", resolution="resolved"), latest_quote=lambda: SimpleNamespace(bid=1, ask=2, spread_points=1, is_stale=False)))
    assert await c._demo_account_authorized() is False

@pytest.mark.asyncio
async def test_live_trading_enabled():
    fake = gold_terminal_with_live_tick()
    fake.account = FakeAccountInfo(trade_mode=0, trade_allowed=True, trade_expert=True)
    settings = make_settings(live_trading_enabled=True)
    conn = MT5Connection(settings, mt5_module=fake)
    await conn.initialize()
    c = AutoTradingController(settings, conn, SimpleNamespace(symbol_status=SimpleNamespace(requested="XAUUSD", resolved="XAUUSD", resolution="resolved"), latest_quote=lambda: SimpleNamespace(bid=1, ask=2, spread_points=1, is_stale=False)))
    assert await c._demo_account_authorized() is False

@pytest.mark.asyncio
async def test_order_send_not_called_when_unauthorized():
    fake = gold_terminal_with_live_tick()
    fake.account = FakeAccountInfo(trade_mode=2, trade_allowed=True, trade_expert=True)
    settings = make_settings()
    conn = MT5Connection(settings, mt5_module=fake)
    await conn.initialize()
    c = AutoTradingController(settings, conn, SimpleNamespace(symbol_status=SimpleNamespace(requested="XAUUSD", resolved="XAUUSD", resolution="resolved"), latest_quote=lambda: SimpleNamespace(bid=1, ask=2, spread_points=1, is_stale=False)))
    # preflight should fail
    with pytest.raises(RuntimeError):
        await c._preflight()
    assert len([x for x in fake.calls if x[0] == "order_send"]) == 0