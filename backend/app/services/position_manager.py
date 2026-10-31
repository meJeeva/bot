"""Position management for the M1 Trend Pullback strategy.

Handles break-even and ATR trailing stop updates for open strategy positions.
Uses the existing MT5 connection; no second execution engine.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from ..logging_config import get_logger
from ..strategy.trend_pullback import atr_series, completed_candles, to_candle
from ..strategy.trend_pullback import normalize_price

logger = get_logger(__name__)

TRADE_ACTION_SLTP = 6


class TrendPullbackPositionManager:
    def __init__(self, settings: Any, connection: Any, monitor: Any) -> None:
        self.settings = settings
        self.connection = connection
        self.monitor = monitor
        self._favorable: Dict[int, float] = {}
        self._last_sl: Dict[int, float] = {}

    def _cfg(self, name: str, default: Any) -> Any:
        return getattr(self.settings, name, default)

    def _enabled(self) -> bool:
        return bool(self._cfg("trend_pullback_be_enabled", False)) or bool(
            self._cfg("trend_pullback_trailing_enabled", False)
        )

    async def _fetch_candles(self, timeframe: str) -> List[Any]:
        series = None
        getter = getattr(self.monitor, "get_candles", None)
        if callable(getter):
            try:
                series = await getter(timeframe, getattr(self.settings, "candle_limit", 300))
            except TypeError:
                try:
                    series = await getter(timeframe)
                except Exception:
                    series = None
            except Exception:
                series = None
        if series is None:
            cached = getattr(self.monitor, "candle_series", None)
            if callable(cached):
                try:
                    series = cached(timeframe)
                except Exception:
                    series = None
        if series is None:
            return []
        candles = getattr(series, "candles", None)
        if candles is None:
            return list(series) if isinstance(series, (list, tuple)) else []
        return list(candles)

    async def _demo_authorized(self) -> bool:
        try:
            if bool(getattr(self.settings, "live_trading_enabled", False)):
                return False
            if bool(getattr(self.settings, "auto_trade_demo_only", True)):
                if not bool(getattr(self.settings, "auto_trade_demo_authorized", False)):
                    return False
            if not await self.connection.acall(self.connection.is_connected):
                return False
            account = await self.connection.acall(self.connection.mt5.account_info)
            if account is None:
                return False
            try:
                if int(getattr(account, "trade_mode", -1)) != 0:
                    return False
            except (TypeError, ValueError):
                return False
            if not bool(getattr(account, "trade_allowed", False)):
                return False
            if not bool(getattr(account, "trade_expert", False)):
                return False
            return True
        except Exception:
            return False

    async def manage(self) -> None:
        if not self._enabled():
            return
        if not await self._demo_authorized():
            return
        symbol = None
        try:
            status = getattr(self.monitor, "symbol_status", None)
            symbol = getattr(status, "resolved", None) or getattr(status, "requested", None)
        except Exception:
            symbol = None
        if symbol is None:
            return

        quote = self.monitor.latest_quote() if hasattr(self.monitor, "latest_quote") else None
        if quote is None or getattr(quote, "is_stale", False):
            return

        mt5 = self.connection.mt5
        try:
            positions = await self.connection.acall(mt5.positions_get, symbol=symbol)
        except Exception:
            try:
                positions = await self.connection.acall(mt5.positions_get)
            except Exception:
                positions = []
        if not positions:
            # clear stale state
            self._favorable.clear()
            self._last_sl.clear()
            return

        magic = getattr(self.settings, "auto_trade_magic_number", None)
        strategy_positions = [
            p for p in positions
            if magic is None or getattr(p, "magic", None) == magic
        ]

        # ATR from completed M1 candles
        tf = getattr(self.settings, "trend_pullback_entry_timeframe", "M1")
        try:
            tf = str(tf).upper()
        except Exception:
            tf = "M1"
        m1 = await self._fetch_candles(tf)
        m1c = completed_candles(m1)
        atr_period = int(self._cfg("trend_pullback_trailing_atr_period", 14))
        from ..mt5.market_data import atr_series as _atr_series

        atr_vals = _atr_series(m1c, atr_period)
        atr = None
        for v in reversed(atr_vals):
            if not (isinstance(v, float) and math.isnan(v)):
                atr = float(v)
                break
        if atr is None or atr <= 0:
            # cannot manage without ATR; skip but do not remove protection
            return

        point = float(getattr(quote, "point", 0.01) or 0.01)
        tick_size = getattr(quote, "tick_size", None)
        digits = None
        try:
            info = await self.connection.acall(mt5.symbol_info, symbol)
            digits = getattr(info, "digits", None)
            stop_level_points = float(getattr(info, "trade_stops_level", 0) or 0)
            freeze_level_points = float(getattr(info, "trade_freeze_level", 0) or 0)
        except Exception:
            info = None
            stop_level_points = 0.0
            freeze_level_points = 0.0

        spread_points = float(getattr(quote, "spread_points", 0) or 0)

        be_enabled = bool(self._cfg("trend_pullback_be_enabled", False))
        be_mult = float(self._cfg("trend_pullback_be_atr_multiplier", 0.6))
        be_min_spread_mult = float(self._cfg("trend_pullback_be_min_spread_multiplier", 2.0))
        be_buffer_points = float(self._cfg("trend_pullback_be_buffer_points", 5.0))

        trail_enabled = bool(self._cfg("trend_pullback_trailing_enabled", False))
        trail_mult = float(self._cfg("trend_pullback_trailing_atr_multiplier", 0.8))
        trail_min_dist_points = float(self._cfg("trend_pullback_trailing_min_distance_points", 10.0))

        for pos in strategy_positions:
            ticket = getattr(pos, "ticket", None)
            if ticket is None:
                continue
            pos_type = getattr(pos, "type", 0)
            entry = float(getattr(pos, "price_open", 0.0) or 0.0)
            current_sl = getattr(pos, "sl", 0.0)
            try:
                current_sl = float(current_sl) if current_sl is not None else 0.0
            except Exception:
                current_sl = 0.0
            tp = getattr(pos, "tp", 0.0)

            # favorable price tracking
            if pos_type == 0:  # BUY
                price_now = float(getattr(quote, "bid", entry) or entry)
                prev = self._favorable.get(ticket, entry)
                self._favorable[ticket] = max(prev, price_now)
            else:  # SELL
                price_now = float(getattr(quote, "ask", entry) or entry)
                prev = self._favorable.get(ticket, entry)
                self._favorable[ticket] = min(prev, price_now)

            favorable = self._favorable.get(ticket, entry)

            candidates: List[float] = []

            # Break-even
            if be_enabled:
                if pos_type == 0:
                    threshold = entry + atr * be_mult + (spread_points * point * be_min_spread_mult)
                    if price_now >= threshold:
                        cand = entry + be_buffer_points * point
                        candidates.append(cand)
                else:
                    threshold = entry - atr * be_mult - (spread_points * point * be_min_spread_mult)
                    if price_now <= threshold:
                        cand = entry - be_buffer_points * point
                        candidates.append(cand)

            # Trailing
            if trail_enabled:
                if pos_type == 0:
                    cand = favorable - atr * trail_mult
                    # min distance from current price
                    if (price_now - cand) >= (trail_min_dist_points * point):
                        candidates.append(cand)
                else:
                    cand = favorable + atr * trail_mult
                    if (cand - price_now) >= (trail_min_dist_points * point):
                        candidates.append(cand)

            if not candidates:
                continue

            if pos_type == 0:
                candidate = max(candidates)
            else:
                candidate = min(candidates)

            candidate = normalize_price(candidate, tick_size, digits)
            if candidate is None:
                continue

            # never move backwards / never remove protection
            if current_sl and current_sl > 0:
                if pos_type == 0 and candidate <= current_sl + (point * 0.5):
                    continue
                if pos_type == 1 and candidate >= current_sl - (point * 0.5):
                    continue
            else:
                # no existing SL: do not set via manager? require protection; skip
                continue

            # stop/freeze level checks
            if pos_type == 0:
                if (price_now - candidate) < (max(stop_level_points, freeze_level_points, trail_min_dist_points) * point - 1e-9):
                    continue
            else:
                if (candidate - price_now) < (max(stop_level_points, freeze_level_points, trail_min_dist_points) * point - 1e-9):
                    continue

            # avoid excessive modifications: if candidate same as last_sl skip
            last = self._last_sl.get(ticket)
            if last is not None and abs(last - candidate) <= (point * 0.5):
                continue

            # modify
            try:
                request = {
                    "action": getattr(mt5, "TRADE_ACTION_SLTP", TRADE_ACTION_SLTP),
                    "symbol": symbol,
                    "position": ticket,
                    "sl": candidate,
                    "tp": tp,
                    "magic": getattr(pos, "magic", getattr(self.settings, "auto_trade_magic_number", 0)),
                }
                result = await self.connection.acall(mt5.order_send, request)
                retcode = getattr(result, "retcode", None)
                done_code = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
                if retcode == done_code:
                    self._last_sl[ticket] = candidate
                    logger.info("Position %s SL updated to %s", ticket, candidate)
                else:
                    logger.warning("SL modification rejected for %s: %s", ticket, getattr(result, "comment", retcode))
            except Exception as exc:
                logger.warning("SL modification failed for %s: %s", ticket, exc)