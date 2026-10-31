"""Historical backtesting for the M1 Trend Pullback strategy.

Separate from live execution. Uses completed candles only and reports metrics.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence

from app.strategy.trend_pullback import (
    TrendPullbackConfig,
    _cfg,
    atr_series,
    buy_stop_loss,
    buy_trigger_price,
    completed_candles,
    ema_series,
    find_pullback,
    m5_trend,
    sell_stop_loss,
    sell_trigger_price,
    to_candle,
    to_candles,
)


@dataclass
class BacktestTrade:
    direction: str
    entry_time: Any
    exit_time: Any
    entry_price: float
    exit_price: float
    sl: float
    volume: float = 1.0
    pnl: float = 0.0
    result: str = ""  # win/loss


def _time(c):
    return getattr(c, "open_time", None)


def run_backtest(
    m1_candles: Sequence[Any],
    m5_candles: Sequence[Any],
    config: Any = None,
    *,
    initial_balance: float = 10000.0,
    point: float = 0.01,
    tick_size: Optional[float] = None,
    digits: Optional[int] = None,
    spread_points: float = 5.0,
    commission_per_trade: float = 0.0,
    slippage_points: float = 1.0,
    volume: float = 1.0,
    max_hold_candles: int = 60,
    **kwargs: Any,
) -> dict:
    cfg = _cfg(config, **kwargs) if config is not None or kwargs else TrendPullbackConfig()
    if isinstance(config, TrendPullbackConfig):
        cfg = config
    m1 = completed_candles(m1_candles)
    m5 = completed_candles(m5_candles)
    if not m1:
        return _empty_result(initial_balance)

    # map m1 index -> available m5 candles
    trades: List[BacktestTrade] = []
    equity = initial_balance
    equity_curve = [initial_balance]
    balance = initial_balance

    # state
    pending_signal = None  # dict with trigger, sl, direction, expiry_index, conf_index
    position = None  # dict

    n = len(m1)
    i = 0
    # need at least lookback+2
    while i < n:
        # manage open position
        if position is not None:
            c = m1[i]
            # check SL
            hit_sl = False
            exit_price = None
            if position["direction"] == "BUY":
                if c.low <= position["sl"]:
                    hit_sl = True
                    exit_price = position["sl"]
                # trailing not modeled beyond initial; break-even could be added but skip
            else:
                if c.high >= position["sl"]:
                    hit_sl = True
                    exit_price = position["sl"]
            if hit_sl:
                # apply slippage
                if position["direction"] == "BUY":
                    exit_price = exit_price - slippage_points * point
                else:
                    exit_price = exit_price + slippage_points * point
                pnl = _pnl(position["direction"], position["entry_price"], exit_price, volume, point)
                pnl -= commission_per_trade
                # spread cost at entry already? include spread half
                trade = BacktestTrade(
                    direction=position["direction"],
                    entry_time=position["entry_time"],
                    exit_time=c.open_time,
                    entry_price=position["entry_price"],
                    exit_price=exit_price,
                    sl=position["sl"],
                    volume=volume,
                    pnl=pnl,
                    result="win" if pnl > 0 else "loss",
                )
                trades.append(trade)
                balance += pnl
                equity = balance
                equity_curve.append(equity)
                position = None
                i += 1
                continue
            # max hold
            if i - position["entry_index"] >= max_hold_candles:
                exit_price = c.close
                pnl = _pnl(position["direction"], position["entry_price"], exit_price, volume, point)
                pnl -= commission_per_trade
                trade = BacktestTrade(
                    direction=position["direction"],
                    entry_time=position["entry_time"],
                    exit_time=c.open_time,
                    entry_price=position["entry_price"],
                    exit_price=exit_price,
                    sl=position["sl"],
                    volume=volume,
                    pnl=pnl,
                    result="win" if pnl > 0 else "loss",
                )
                trades.append(trade)
                balance += pnl
                equity = balance
                equity_curve.append(equity)
                position = None
                i += 1
                continue
            equity_curve.append(equity)
            i += 1
            continue

        # pending signal breakout check
        if pending_signal is not None:
            # expiration
            if i > pending_signal["expiry_index"]:
                pending_signal = None
                i += 1
                continue
            c = m1[i]
            if pending_signal["direction"] == "BUY":
                if c.high >= pending_signal["trigger"]:
                    # enter
                    entry_price = pending_signal["trigger"] + slippage_points * point + (spread_points * point / 2.0)
                    position = {
                        "direction": "BUY",
                        "entry_price": entry_price,
                        "sl": pending_signal["sl"],
                        "entry_time": c.open_time,
                        "entry_index": i,
                    }
                    pending_signal = None
                    i += 1
                    continue
            else:
                if c.low <= pending_signal["trigger"]:
                    entry_price = pending_signal["trigger"] - slippage_points * point - (spread_points * point / 2.0)
                    position = {
                        "direction": "SELL",
                        "entry_price": entry_price,
                        "sl": pending_signal["sl"],
                        "entry_time": c.open_time,
                        "entry_index": i,
                    }
                    pending_signal = None
                    i += 1
                    continue
            i += 1
            continue

        # generate signal at candle i (using completed candles up to i)
        if i < cfg.lookback + 2:
            i += 1
            continue
        window_m1 = m1[: i + 1]
        # available m5 up to this m1 time
        t_i = _time(m1[i])
        if t_i is not None:
            m5_avail = [c for c in m5 if (_time(c) is not None and _time(c) <= t_i)]
        else:
            # group by index: assume 5 m1 per m5
            m5_idx = min(len(m5) - 1, i // 5)
            m5_avail = m5[: m5_idx + 1]
        if len(m5_avail) < max(cfg.fast_ema, cfg.slow_ema) + 2:
            i += 1
            continue
        bias = m5_trend(m5_avail, cfg)
        if bias is None:
            i += 1
            continue
        pullback = find_pullback(window_m1, bias, cfg)
        if pullback is None:
            i += 1
            continue
        if len(window_m1) < 2:
            i += 1
            continue
        conf = window_m1[-1]
        prev = window_m1[-2]
        atr = pullback.atr
        closes = [c.close for c in window_m1]
        fast_vals = ema_series(closes, cfg.fast_ema)
        ema20 = fast_vals[-1] if fast_vals else None
        if bias == "BUY":
            ok = (to_candle(conf).close > to_candle(conf).open) and (ema20 is None or to_candle(conf).close > ema20) and (to_candle(conf).close > to_candle(prev).high)
        else:
            ok = (to_candle(conf).close < to_candle(conf).open) and (ema20 is None or to_candle(conf).close < ema20) and (to_candle(conf).close < to_candle(prev).low)
        # candle size filters
        size = abs(to_candle(conf).close - to_candle(conf).open)
        if atr and (size < cfg.min_candle_atr * atr or size > cfg.max_candle_atr * atr):
            ok = False
        if not ok:
            i += 1
            continue
        # trigger + sl
        if bias == "BUY":
            trigger = buy_trigger_price(conf, config=cfg, point=point)
            sl = buy_stop_loss(pullback, config=cfg, point=point, tick_size=tick_size, digits=digits)
        else:
            trigger = sell_trigger_price(conf, config=cfg, point=point)
            sl = sell_stop_loss(pullback, config=cfg, point=point, tick_size=tick_size, digits=digits)
        if trigger is None or sl is None:
            i += 1
            continue
        pending_signal = {
            "direction": bias,
            "trigger": float(trigger),
            "sl": float(sl),
            "conf_index": i,
            "expiry_index": i + cfg.signal_expiry_candles,
        }
        i += 1

    # close open position at end
    if position is not None:
        c = m1[-1]
        exit_price = c.close
        pnl = _pnl(position["direction"], position["entry_price"], exit_price, volume, point)
        pnl -= commission_per_trade
        trade = BacktestTrade(
            direction=position["direction"],
            entry_time=position["entry_time"],
            exit_time=c.open_time,
            entry_price=position["entry_price"],
            exit_price=exit_price,
            sl=position["sl"],
            volume=volume,
            pnl=pnl,
            result="win" if pnl > 0 else "loss",
        )
        trades.append(trade)
        balance += pnl
        equity_curve.append(balance)

    return _metrics(trades, initial_balance, balance, equity_curve)


def _pnl(direction, entry, exit_price, volume, point):
    if direction == "BUY":
        return (exit_price - entry) * volume / point * point  # price diff * volume? 
    else:
        return (entry - exit_price) * volume


# fix pnl: use price difference * volume (assuming volume units)
def _pnl(direction, entry, exit_price, volume, point):
    diff = (exit_price - entry) if direction == "BUY" else (entry - exit_price)
    return diff * volume


def _empty_result(initial_balance):
    return {
        "initial_balance": initial_balance,
        "final_balance": initial_balance,
        "net_profit": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "profit_factor": 0.0,
        "win_rate": 0.0,
        "total_trades": 0,
        "buy_trades": 0,
        "sell_trades": 0,
        "average_win": 0.0,
        "average_loss": 0.0,
        "max_drawdown": 0.0,
        "max_consecutive_losses": 0,
        "expectancy": 0.0,
        "monthly_performance": {},
        "equity_curve": [initial_balance],
        "trades": [],
    }


def _metrics(trades, initial_balance, final_balance, equity_curve):
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = sum(t.pnl for t in losses)
    net_profit = final_balance - initial_balance
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss != 0 else (float("inf") if gross_profit > 0 else 0.0)
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    avg_win = (sum(t.pnl for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(t.pnl for t in losses) / len(losses)) if losses else 0.0
    # max drawdown
    peak = equity_curve[0] if equity_curve else initial_balance
    max_dd = 0.0
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd
    # max consecutive losses
    max_cl = 0
    cur = 0
    for t in trades:
        if t.pnl <= 0:
            cur += 1
            max_cl = max(max_cl, cur)
        else:
            cur = 0
    expectancy = (net_profit / len(trades)) if trades else 0.0
    # monthly performance
    monthly = defaultdict(float)
    for t in trades:
        key = None
        et = t.exit_time
        if isinstance(et, datetime):
            key = et.strftime("%Y-%m")
        elif isinstance(et, (int, float)):
            try:
                key = datetime.fromtimestamp(et, tz=timezone.utc).strftime("%Y-%m")
            except Exception:
                key = "unknown"
        else:
            key = "unknown"
        monthly[key] += t.pnl
    monthly = dict(monthly)
    return {
        "initial_balance": initial_balance,
        "final_balance": final_balance,
        "net_profit": net_profit,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "total_trades": len(trades),
        "buy_trades": sum(1 for t in trades if t.direction == "BUY"),
        "sell_trades": sum(1 for t in trades if t.direction == "SELL"),
        "average_win": avg_win,
        "average_loss": avg_loss,
        "max_drawdown": max_dd,
        "max_consecutive_losses": max_cl,
        "expectancy": expectancy,
        "monthly_performance": monthly,
        "equity_curve": equity_curve,
        "trades": [t.__dict__ for t in trades],
    }


# aliases
def backtest(*a, **k):
    return run_backtest(*a, **k)

def run(*a, **k):
    return run_backtest(*a, **k)

def backtest_strategy(*a, **k):
    return run_backtest(*a, **k)
