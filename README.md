# MT5 Market Data — read-only

Live **XAUUSD** market data from a MetaTrader 5 desktop terminal, streamed to a
small React dashboard through a Python backend.

> **This build is read-only.**
> There are no trading strategies, no signal generation, no backtesting, no
> shadow simulation and no order execution. The application connects to the
> terminal, reads ticks, candles and account information, and displays them.
> It cannot place, modify or close an order.

---

## What it does

| Capability | Where |
|---|---|
| MT5 terminal connection with discovery, backoff reconnect and clean shutdown | `backend/app/mt5/connection.py` |
| Broker symbol discovery that never silently swaps instruments | `backend/app/mt5/symbols.py` |
| Live ticks: bid, ask, last, spread (price **and** points), freshness | `backend/app/mt5/market_data.py` |
| Historical OHLC for M1, M5, M15, M30, H1, H4, D1 | `backend/app/mt5/market_data.py`, `timeframes.py` |
| Completed vs. forming candle classification on the broker clock | `backend/app/mt5/market_data.py` |
| Continuous background monitoring, independent of the dashboard | `backend/app/services/market_monitor.py` |
| REST API + WebSocket stream | `backend/app/api/` |
| SQLite connection/market telemetry | `backend/app/storage.py` |
| Minimal React screen: connection, symbol and live quote | `frontend/src/` |
| Windows PowerShell setup/start/test scripts | `scripts/` |
| Mock-based tests + genuine MT5 integration tests | `backend/tests/` |

Removed and deleted from the previous build: every Fibonacci/EMA/liquidity/
session/volume strategy, signal generation, candidate registries, backtesting
and optimisation, shadow/forward simulation, risk sizing and the demo execution
pipeline, together with their source, tests, reports, datasets, logs and
archives. Only the read-only market-data application remains.

---

## Architecture

```
MetaTrader 5 desktop terminal
        │  (official MetaTrader5 Python package, single serialised IPC channel)
        ▼
MT5Connection ─────────── owns initialize/shutdown, discovery, backoff reconnect
        │                 every call runs on one worker thread, never the event loop
        ▼
MarketMonitor ─────────── one background asyncio task, polling loop, candle cache
        │                 keeps the latest valid snapshot; marks stale data
        ├────────────► REST API (/api/...)      read cached state only
        │
        └────────────► WS /ws/market ──► React dashboard (Vite)
```

Two design decisions drive everything else:

1. **The HTTP layer never talks to MetaTrader.** Requests only read state the
   monitor already gathered. A hung or disconnected terminal degrades the
   reported *status*; it never blocks or crashes a request.
2. **All MetaTrader calls are serialised onto one worker thread.** The
   `MetaTrader5` package is not thread-safe, so concurrent requests cannot
   corrupt connection state, and long blocking calls stay off the event loop.

The backend runs continuously and independently of the React dashboard.
Closing the browser changes nothing on the backend.

---

## Requirements

| Component | Version | Notes |
|---|---|---|
| Windows | 10 / 11 | MetaTrader 5 is Windows-only |
| Python | **3.10 – 3.12** | The `MetaTrader5` wheel is Windows-only |
| Node.js | 18 or newer | Bundles npm |
| MetaTrader 5 | current build | Installed from your broker; log into a demo account |

---

## Quick start on Windows

Open PowerShell **in the project root**, then:

```powershell
# 1. Verify toolchains, create .venv, install everything, seed .env files
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1

# 2. Make sure the MetaTrader 5 terminal is running and logged in

# 3. Start the backend (http://127.0.0.1:8000)
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1

# 4. In a second terminal, start the dashboard (http://127.0.0.1:5173)
powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend.ps1
```

Run every test suite:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```

---

## Configuration

Settings are loaded from environment variables and `backend/.env`. Copy
`backend/.env.example` to `backend/.env` and adjust:

| Variable | Default | Purpose |
|---|---|---|
| `MT5_SYMBOL` | `XAUUSD` | Symbol to read |
| `MT5_SYMBOL_CANDIDATES` | `XAUUSD,XAUUSD.,XAUUSDm,…` | Discovery order when the broker renames instruments |
| `MT5_TERMINAL_PATH` | *(empty)* | Explicit `terminal64.exe`; empty attaches to the running terminal |
| `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` | *(empty)* | Optional unattended login (never logged or exposed) |
| `POLL_INTERVAL_MS` | `1000` | Tick polling interval |
| `STALE_TICK_THRESHOLD_SECONDS` | `20` | A tick older than this is reported stale |
| `CANDLE_LIMIT` / `MAX_CANDLE_LIMIT` | `300` / `5000` | Candle history bounds |
| `DATABASE_ENABLED` | `true` | SQLite connection/quote telemetry |
| `EXPOSE_ACCOUNT_LOGIN` | `false` | Mask the account login by default |

`APP_READ_ONLY` must remain `true`; the application refuses to start otherwise.

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Backend health; `degraded` whenever data is not live |
| GET | `/api/mt5/status` | Terminal, account (masked) and symbol status |
| GET | `/api/mt5/events` | Recent connection events and errors from SQLite |
| GET | `/api/market/quote` | Latest bid / ask / spread / freshness |
| GET | `/api/market/candles?timeframe=M1&limit=300` | OHLC history (backend only; not shown on the dashboard) |
| GET | `/api/market/snapshot` | Connection + symbol + quote + timeframe summaries |
| GET | `/api/market/timeframes` | Supported timeframes |
| GET | `/api/market/symbols` | Symbol discovery detail |
| WS | `/ws/market` | Snapshot stream + heartbeat |

There is no POST, PUT, PATCH or DELETE route. The OpenAPI document is at
`/docs`.

### Honesty rules

* A price the terminal did not supply is `null`, never `0` and never a stale
  value presented as live.
* A tick older than the freshness threshold makes the whole snapshot `stale`.
* Bars are returned with both the raw broker timestamp and the offset-corrected
  UTC timestamp; `is_closed` distinguishes completed bars from the forming bar.
* A disconnected terminal is a **state** (`200` with
  `terminal_connected: false`), not a fabricated price.

---

## Project layout

```
backend/
  app/
    api/            health, connection, market_data, websocket
    mt5/            connection, market_data, symbols, timeframes
    services/       market_monitor
    schemas/        Pydantic response models
    config.py       environment settings
    storage.py      SQLite telemetry
    main.py         FastAPI factory and lifespan
  tests/            mock-based unit/API tests + `live` MT5 integration tests
frontend/
  src/
    components/     ConnectionStatusCard, QuotePanel
    hooks/          useMarketStream
    services/       api, websocket, dashboardState, format
    pages/          DashboardView
    types/          market contract types
scripts/            setup, start and test helpers
```

---

## Testing

```powershell
# Backend, mock-based suite (no terminal needed)
cd backend; python -m pytest -m "not live"

# A genuine MT5 integration run (needs a running, logged-in terminal)
python -m pytest -m live

# Frontend
cd frontend; npm test; npm run typecheck
```

If the `live` integration test cannot run (no terminal in this environment),
that is reported as a limitation — mock tests never stand in for real
connectivity.

---

## Troubleshooting

### The dashboard says `Disconnected`

The backend is running but the terminal is not reachable. Check that the
MetaTrader 5 terminal is open and logged in, and that `MT5_TERMINAL_PATH` is
either empty or points at the right `terminal64.exe`.

### The dashboard says `Error` and names the MetaTrader5 package

The backend is running, but the `MetaTrader5` Python package is missing from
the virtual environment. Run `scripts/setup_windows.ps1` (or
`pip install -r backend/requirements.txt` inside `.venv`) and restart the
backend. A misconfigured `MT5_TERMINAL_PATH` fails at startup with the same
kind of guidance instead of a raw validation traceback.

### The backend says `Authorization failed` (`-6`)

Open the terminal and log in. Unattended login requires all three of
`MT5_LOGIN`, `MT5_PASSWORD` and `MT5_SERVER`.

### The symbol resolves as `ambiguous`

The broker lists more than one match. Set `MT5_SYMBOL` to the exact name shown
in Market Watch.

### Data is `stale`

The terminal is connected but its newest tick is older than
`STALE_TICK_THRESHOLD_SECONDS` (often a closed market). The dashboard will not
pretend the old price is live.
