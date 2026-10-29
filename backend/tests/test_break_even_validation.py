"""Break-even stop-loss validation regression tests.

Background: on a controlled XAUUSD demo run, two break-even SLTP
modifications were rejected with ``10016 Invalid stops`` and the third
attempt succeeded.  The cause was that the submission path never
re-validated the proposed stop against a fresh tick on the market side
that executes it (Bid for a BUY, Ask for a SELL), re-read the broker's
stop/freeze restrictions, or confirmed the position still existed.

These tests pin that behaviour.  Everything here is mocked; no real
order is ever submitted.
"""

from __future__ import annotations

import pytest

from tests.auto_trading_harness import (
    VirtualClock,
    build_controller,
    install_virtual_time,
)
from tests.fakes import (
    FakeOrderResult,
    FakePosition,
    FakeTick,
    TRADE_ACTION_SLTP,
    broker_time,
    gold_terminal_with_live_tick,
)


MAGIC = 9001

_BUY = 0
_SELL = 1


def _sltp_requests(fake):
    """Every SLTP ``order_send`` request the fake observed."""
    requests = []
    for name, args, _kwargs in fake.calls:
        if name == "order_send" and args and isinstance(args[0], dict):
            if args[0].get("action") == TRADE_ACTION_SLTP:
                requests.append(args[0])
    return requests


async def _seeded_controller(monkeypatch, side: str, *, sl: float):
    """A stopped-out-of-the-box controller holding one adopted position.

    The worker loop is never started, so each test controls every
    ``_move_stop`` call deterministically.
    """
    clock = VirtualClock()
    install_virtual_time(monkeypatch, clock)
    fake = gold_terminal_with_live_tick()
    controller, _connection, _settings = await build_controller(
        fake,
        auto_trade_entry_offset=1.00,
        auto_trade_break_even_offset=0.40,
        auto_trade_trailing_distance=0.40,
    )
    bid = fake.ticks["XAUUSD"].bid
    ask = fake.ticks["XAUUSD"].ask
    position = FakePosition(
        ticket=9001 if side == "buy" else 9002,
        symbol="XAUUSD",
        magic=MAGIC,
        volume=0.01,
        price_open=(bid - 0.01) if side == "buy" else (ask - 0.01),
        sl=sl,
        type=_BUY if side == "buy" else _SELL,
    )
    fake.orders = []
    fake.positions = [position]
    controller._position = position
    controller._position_ticket = position.ticket
    controller._active_side = side
    controller._entry_price = position.price_open
    controller._current_sl = sl
    return controller, clock, fake, position, bid, ask


@pytest.mark.asyncio
async def test_buy_stop_validated_against_bid_not_ask(monkeypatch):
    """A BUY stop executes at the Bid: it must sit strictly below it."""
    controller, clock, fake, position, bid, ask = await _seeded_controller(
        monkeypatch, "buy", sl=4180.0
    )

    # A target between the Bid and the Ask is above the Bid and therefore
    # wrong for a BUY, even though it is below the Ask.
    between = (bid + ask) / 2.0
    before = len(_sltp_requests(fake))
    result = await controller._move_stop(position, "buy", between, reason="between")
    assert result is False
    assert len(_sltp_requests(fake)) == before, "wrong-side BUY stop must not be submitted"
    assert "must sit below the Bid" in (controller._last_broker_result or "")

    # A strictly-below-Bid target is the correct market side.
    clock.advance(2.0)
    result = await controller._move_stop(position, "buy", bid - 0.01, reason="correct side")
    assert result is True
    assert len(_sltp_requests(fake)) == before + 1
    submitted = _sltp_requests(fake)[-1]
    assert submitted["sl"] == pytest.approx(bid - 0.01, abs=1e-6)
    assert submitted["position"] == position.ticket


@pytest.mark.asyncio
async def test_sell_stop_validated_against_ask_not_bid(monkeypatch):
    """A SELL stop executes at the Ask: it must sit strictly above it."""
    controller, clock, fake, position, bid, ask = await _seeded_controller(
        monkeypatch, "sell", sl=4200.0
    )

    # A target between the Bid and the Ask is below the Ask and therefore
    # wrong for a SELL, even though it sits above the Bid.  Validating the
    # SELL against the Bid would (wrongly) accept it; the Ask must be used.
    between = (bid + ask) / 2.0
    before = len(_sltp_requests(fake))
    result = await controller._move_stop(position, "sell", between, reason="between")
    assert result is False
    assert len(_sltp_requests(fake)) == before, "wrong-side SELL stop must not be submitted"
    assert "must sit above the Ask" in (controller._last_broker_result or "")

    # A strictly-above-Ask target is the correct market side, and it is a
    # protective move for a SELL because it sits below the current SL 4200.
    assert ask + 0.05 < controller._current_sl
    clock.advance(2.0)
    result = await controller._move_stop(position, "sell", ask + 0.05, reason="correct side")
    assert result is True
    assert len(_sltp_requests(fake)) == before + 1
    submitted = _sltp_requests(fake)[-1]
    assert submitted["sl"] == pytest.approx(ask + 0.05, abs=1e-6)


@pytest.mark.asyncio
async def test_stop_level_restriction_uses_point_units(monkeypatch):
    """A stop closer than the broker's stops_level (in points) is deferred."""
    controller, clock, fake, position, bid, ask = await _seeded_controller(
        monkeypatch, "buy", sl=4180.0
    )
    # 120 points with point=0.01 => a 1.20 price-unit minimum stop distance.
    fake.symbols[0].trade_stops_level = 120

    too_close = bid - 0.50
    before = len(_sltp_requests(fake))
    result = await controller._move_stop(position, "buy", too_close, reason="too close")
    assert result is False
    assert len(_sltp_requests(fake)) == before, "stop inside stops_level must be deferred"
    assert "the broker requires 1.2" in (controller._last_broker_result or "")
    assert "stops_level=120" in (controller._last_broker_result or "")

    # Far enough from the Bid: accepted.
    clock.advance(2.0)
    result = await controller._move_stop(position, "buy", bid - 1.30, reason="far enough")
    assert result is True
    assert len(_sltp_requests(fake)) == before + 1


@pytest.mark.asyncio
async def test_freeze_level_blocks_modification_near_the_market(monkeypatch):
    """While the broker's current SL sits inside the freeze zone nothing is sent."""
    controller, clock, fake, position, bid, ask = await _seeded_controller(
        monkeypatch, "sell", sl=4186.14 + 0.30
    )
    # 40 points with point=0.01 => a 0.40 price-unit freeze distance.
    fake.symbols[0].trade_freeze_level = 40

    before = len(_sltp_requests(fake))
    # The target itself is a valid, protective SELL stop (below the broker's
    # SL, above the Ask), but the broker's CURRENT stop is only 0.30 from
    # the Ask and therefore inside the freeze zone.
    result = await controller._move_stop(position, "sell", ask + 0.10, reason="tighten")
    assert result is False
    assert len(_sltp_requests(fake)) == before, "frozen SLTP must not be submitted"
    assert "frozen within 0.4" in (controller._last_broker_result or "")

    # Once the market falls away from the broker's SL the same modification
    # is accepted against a fresh tick.
    moved = FakeTick(time=broker_time(), bid=ask - 2.10, ask=ask - 2.00)
    fake.ticks["XAUUSD"] = moved
    clock.advance(2.0)
    result = await controller._move_stop(position, "sell", moved.ask + 0.10, reason="away now")
    assert result is True
    assert len(_sltp_requests(fake)) == before + 1


@pytest.mark.asyncio
async def test_market_moving_after_validation_yields_a_rejection_not_a_success(monkeypatch):
    """A quote that moves between validation and submission is handled."""
    controller, clock, fake, position, bid, ask = await _seeded_controller(
        monkeypatch, "buy", sl=4180.0
    )

    # Validated against the current tick (bid=4185.58): bid - 0.02 is valid.
    target = pytest.approx(bid - 0.02, abs=1e-6)
    level = bid - 0.02

    # While the request is in flight the market falls below the submitted
    # SL, so the broker answers 10016 invalid stops.
    moved = FakeTick(time=broker_time(), bid=bid - 0.20, ask=bid - 0.14)

    def moving_send(request):
        fake.ticks["XAUUSD"] = moved  # market moves during transit
        return _original_send(request)

    _original_send = fake.order_send
    fake.order_send = moving_send
    fake.order_send_results = [FakeOrderResult(retcode=10016, comment="Invalid stops")]

    result = await controller._move_stop(position, "buy", level, reason="transit")
    assert result is False, "a rejected modification must never be reported as success"
    # The rejected level is recorded so the identical request is not repeated.
    assert controller._rejected_sl_level == pytest.approx(level, abs=1e-6)
    # The broker's still-valid protective SL is reconciled, preserved.
    assert controller._current_sl == pytest.approx(4180.0, abs=1e-6)
    assert position.sl == pytest.approx(4180.0, abs=1e-6)
    assert "rejected" in (controller._last_exit_result or "")

    fake.order_send = _original_send


@pytest.mark.asyncio
async def test_rejected_modification_followed_by_a_valid_later_retry(monkeypatch):
    controller, clock, fake, position, bid, ask = await _seeded_controller(
        monkeypatch, "buy", sl=4180.0
    )
    fake.order_send_results = [
        FakeOrderResult(retcode=10016, comment="Invalid stops"),
        FakeOrderResult(retcode=10009, comment="ok"),
    ]

    first = bid - 0.02
    result = await controller._move_stop(position, "buy", first, reason="attempt one")
    assert result is False
    assert len(_sltp_requests(fake)) == 1

    # Later scheduler cycle: a new, more protective and still-valid target.
    clock.advance(2.0)
    second = bid - 0.10
    assert second > controller._current_sl  # protective
    result = await controller._move_stop(position, "buy", second, reason="attempt two")
    assert result is True
    assert len(_sltp_requests(fake)) == 2
    assert _sltp_requests(fake)[-1]["sl"] == pytest.approx(second, abs=1e-6)
    # The broker's actual stored SL is confirmed after success.
    assert controller._current_sl == pytest.approx(second, abs=1e-6)
    assert controller._rejected_sl_level is None


@pytest.mark.asyncio
async def test_already_closed_position_is_not_modified(monkeypatch):
    controller, clock, fake, position, bid, ask = await _seeded_controller(
        monkeypatch, "buy", sl=4180.0
    )
    fake.positions = []  # the position was closed (e.g. stop-loss hit)

    before = len(_sltp_requests(fake))
    result = await controller._move_stop(position, "buy", bid - 0.10, reason="stale")
    assert result is False
    assert len(_sltp_requests(fake)) == before, "a closed position must never be modified"
    assert "no longer open" in (controller._last_broker_result or "")
    # Not a recoverable defer: no retry window is scheduled for a dead ticket.
    assert controller._sl_retry_at == 0.0


@pytest.mark.asyncio
async def test_broker_side_sl_preserved_after_failure(monkeypatch):
    controller, clock, fake, position, bid, ask = await _seeded_controller(
        monkeypatch, "buy", sl=4180.0
    )
    fake.order_send_results = [FakeOrderResult(retcode=10016, comment="Invalid stops")]

    result = await controller._move_stop(position, "buy", bid - 0.02, reason="attempt")
    assert result is False
    # The broker's actual stored SL survives the failed attempt untouched.
    assert position.sl == pytest.approx(4180.0, abs=1e-6)
    assert controller._current_sl == pytest.approx(4180.0, abs=1e-6)
    assert fake.positions[0].sl == pytest.approx(4180.0, abs=1e-6)
    # The precise reason is recorded, and the position stays managed (the
    # tracked ticket and side are not dropped).
    assert "retcode=10016" in (controller._last_broker_result or "")
    assert controller._position_ticket == position.ticket
    assert controller._active_side == "buy"


@pytest.mark.asyncio
async def test_repeated_identical_rejected_request_is_never_resent(monkeypatch):
    controller, clock, fake, position, bid, ask = await _seeded_controller(
        monkeypatch, "buy", sl=4180.0
    )
    fake.order_send_results = [
        FakeOrderResult(retcode=10016, comment="Invalid stops"),
        FakeOrderResult(retcode=10009, comment="ok"),
    ]

    first = bid - 0.02
    result = await controller._move_stop(position, "buy", first, reason="attempt one")
    assert result is False
    assert controller._rejected_sl_level == pytest.approx(first, abs=1e-6)

    # After the retry window the identical target is still broker-rejected:
    # it must be withheld instead of resubmitted blindly.
    clock.advance(2.0)
    before = len(_sltp_requests(fake))
    result = await controller._move_stop(position, "buy", first, reason="attempt one again")
    assert result is False
    assert len(_sltp_requests(fake)) == before, "the identical rejected SL must not be resent"

    # Only a new, more protective (and market-valid) target is submitted.
    clock.advance(2.0)
    second = bid - 0.01
    result = await controller._move_stop(position, "buy", second, reason="attempt two")
    assert result is True
    assert len(_sltp_requests(fake)) == before + 1
    assert _sltp_requests(fake)[-1]["sl"] == pytest.approx(second, abs=1e-6)
