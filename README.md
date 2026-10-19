# Fibonacci MT5 Bot — Phase 1

Live **XAUUSD** market data from a MetaTrader 5 desktop terminal, streamed to a
React dashboard through a Python backend.

> **This is Phase 1: infrastructure only.**
> There is no strategy, no signal generation and no order execution. The
> application is strictly read-only and cannot place, modify or close an order.
> Fibonacci swing detection, trade signals and execution arrive in later phases.

---

## Contents

- [What Phase 1 delivers](#what-phase-1-delivers)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Quick start on Windows](#quick-start-on-windows)
- [Configuration](#configuration)
- [Running the application](#running-the-application)
- [API reference](#api-reference)
- [Testing](#testing)
- [How the tricky parts work](#how-the-tricky-parts-work)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Phase boundaries](#phase-boundaries)
- [Handover to Phase 2](#handover-to-phase-2)

---

## What Phase 1 delivers

| Capability | Where |
|---|---|
| MT5 terminal connection with discovery, backoff reconnect and clean shutdown | `backend/app/mt5/connection.py` |
| Broker symbol discovery that never silently swaps instruments | `backend/app/mt5/symbols.py` |
| Live ticks: bid, ask, last, spread (price **and** points), freshness | `backend/app/mt5/market_data.py` |
| Historical OHLC for M1, M5, M15, M30, H1, H4, D1 | `backend/app/mt5/market_data.py`, `timeframes.py` |
| Continuous background monitoring, independent of the dashboard | `backend/app/services/market_monitor.py` |
| REST API + WebSocket stream | `backend/app/api/` |
| SQLite connection/market telemetry | `backend/app/storage.py` |
| React dashboard with live chart and honest status states | `frontend/src/` |
| Windows PowerShell setup/start/test scripts | `scripts/` |
| Mock-based tests + genuine MT5 integration tests | `backend/tests/` |

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
        ├────────────► RESTAPI  (/api/...)      read cached state only
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

The Python backend therefore runs continuously and independently of the React
dashboard. Closing the browser changes nothing on the backend.

---

## Requirements

| Component | Version | Notes |
|---|---|---|
| Windows | 10 / 11 | MetaTrader 5 is Windows-only |
| Python | **3.10 – 3.12** | Tested on 3.12.2. The `MetaTrader5` wheel is Windows-only. |
| Node.js | 18 or newer | Tested on Node 24. Bundles npm. |
| MetaTrader 5 | current build | Installed from your broker, logged into a **demo** account |

> Do not use Python 3.13+ unless a matching `MetaTrader5` wheel is available.

---

## Quick start on Windows

Open PowerShell **in the project root**, then:

```powershell
# 1. Verify toolchains, create .venv, install everything, seed .env files
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1

# 2. Make sure the MetaTrader 5 terminal is running and logged into a demo account

# 3. Terminal A - backend
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1

# 4. Terminal B - dashboard
powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend.ps1
```

Then open <http://localhost:5173>. API documentation is at
<http://127.0.0.1:8000/docs>.

The backend and frontend are **separate development processes** and are started
from separate terminals on purpose.

### Manual setup (if you prefer not to use the script)

```powershell
# Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env

# Frontend
cd frontend
npm install
Copy-Item .env.example .env
cd ..
```

### Running without the scripts

```powershell
# Backend (from the `backend` directory, inside the virtual environment)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Frontend (from the `frontend` directory)
npm run dev
```

### Stopping safely

Press **Ctrl+C** in the backend terminal. The shutdown path stops the monitoring
loop, releases the MetaTrader connection and closes the SQLite store cleanly.
Press Ctrl+C in the frontend terminal to stop Vite.

---

## Configuration

Two files, both created from their `.env.example` templates by the setup script
and both git-ignored:

| File | Consumed by | Purpose |
|---|---|---|
| `backend/.env` | Python backend | MT5, polling, logging, persistence, CORS |
| `frontend/.env` | Vite dashboard | API and WebSocket URLs |

Every backend value is validated at startup. An invalid value stops the process
with a message naming the exact field rather than leaving a half-configured
server running. See [`backend/.env.example`](backend/.env.example) for the full
annotated list.

The settings most worth knowing:

| Setting | Default | Meaning |
|---|---|---|
| `MT5_SYMBOL` | `XAUUSD` | The instrument to read. Set the broker's **exact** name if it differs. |
| `MT5_TERMINAL_PATH` | *(empty)* | Pin one terminal install. Empty enables automatic discovery. |
| `MT5_SYMBOL_CANDIDATES` | `XAUUSD,XAUUSD.,XAUUSDm,...` | Extra names to probe. Never breaks a tie (see below). |
| `POLL_INTERVAL_MS` | `1000` | Tick polling interval. |
| `STALE_TICK_THRESHOLD_SECONDS` | `20` | A tick older than this is reported as **stale**, never live. |
| `CANDLE_LIMIT` / `MAX_CANDLE_LIMIT` | `300` / `5000` | Default and hard cap for `/api/market/candles`. |
| `ALLOWED_ORIGINS` | localhost:5173 | CORS allow-list. A wildcard is rejected when `APP_ENV=production`. |
| `APP_READ_ONLY` | `true` | Safety switch. The backend **refuses to start** if set to false. |
| `DATABASE_ENABLED` | `true` | Optional SQLite telemetry. The app runs fine with it off. |

### Credentials

The preferred mode is an **already-authenticated terminal session** — start MT5,
log in, and leave the backend credential settings empty. `MT5_LOGIN`,
`MT5_PASSWORD` and `MT5_SERVER` exist only for unattended machines.

Passwords are never written to logs (a redaction filter scrubs credential-shaped
values from every record) and are never exposed through the API. Account logins
are masked by default (`******7615`); set `EXPOSE_ACCOUNT_LOGIN=true` only on a
trusted local machine.

---

## API reference

Interactive documentation: **<http://127.0.0.1:8000/docs>** (`/redoc` for the
alternative rendering, `/openapi.json` for the raw schema).

### REST

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/health` | Backend status, version, uptime, MT5 flags |
| `GET` | `/api/mt5/status` | Safe terminal/account status + resolved symbol |
| `GET` | `/api/mt5/events?limit=10` | Recent connection events and errors |
| `GET` | `/api/market/quote` | Latest bid, ask, spread, tick time, freshness |
| `GET` | `/api/market/candles?timeframe=M15&limit=300` | OHLC history for one timeframe |
| `GET` | `/api/market/snapshot` | Connection + symbol + quote + all timeframes |
| `GET` | `/api/market/symbols` | Symbol discovery detail (ambiguity diagnostics) |
| `GET` | `/api/market/timeframes` | The seven supported timeframes and their MT5 constants |

`GET /api/market/candles` accepts **only** `M1`, `M5`, `M15`, `M30`, `H1`, `H4`
and `D1` (case-insensitive). Anything else is `400 unsupported_timeframe` with
the supported list in `error.detail.supported`. A `limit` outside
`1..MAX_CANDLE_LIMIT` is `400 invalid_limit`.

**Timestamps.** MetaTrader returns *broker-server local time*. Every timestamp
is published twice: the raw MetaTrader value, and an offset-corrected UTC value
(`open_time_utc` / `tick_time_utc`). The correction comes from a **measured**
offset, exposed as `server_time_offset_seconds` — never an assumption.

**Forming vs completed bars.** `latest_candle` is the bar still forming;
`latest_closed_candle` is the newest bar that is definitely complete. Each bar
carries an `is_closed` boolean. Never treat the forming bar as finished.

**Unavailable values are `null`.** A missing, zero or inverted price is reported
as `null`, never as `0` and never as a fabricated replacement.

### WebSocket

```
ws://127.0.0.1:8000/ws/market
```

- Sends a full snapshot immediately on connect.
- Sends another whenever market data actually changes (or at least once per
  `WS_PUSH_INTERVAL_MS`).
- Supports many simultaneous clients. Each gets a **bounded** queue
  (`WS_MAX_QUEUE`); a slow client has its oldest frame dropped, so memory cannot
  grow without limit.
- Sends `{"type":"heartbeat"}` when idle, which also detects vanished clients.
- Keeps streaming through an MT5 disconnect by reporting `stale` /
  `unavailable` state, and recovers automatically when the terminal returns.

Frame types: `snapshot`, `heartbeat`, `status`, `error`.

### Error format

Every failure uses one envelope:

```json
{ "error": { "code": "unsupported_timeframe", "message": "...", "detail": { "supported": ["M1", "..."] } } }
```

---

## Testing

```powershell
# Mock-based suites only (no terminal required)
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1

# Also run the genuine MetaTrader 5 integration tests
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1 -IncludeLive

# Only the live integration tests
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1 -LiveOnly
```

Or directly:

```powershell
# Backend
cd backend
..\.venv\Scripts\python.exe -m pytest                  # full suite
..\.venv\Scripts\python.exe -m pytest -m "not live"    # mocks only
..\.venv\Scripts\python.exe -m pytest -m live -v -s    # live MT5 only

# Frontend
cd frontend
npm run test
npm run typecheck
```

### Mock tests vs live tests

This distinction is deliberate and important:

- **`backend/tests/` (excluding `integration/`)** runs against
  `tests/fakes.FakeMT5`. These tests prove the application *logic*. They are
  **not** evidence that MetaTrader is reachable.
- **`backend/tests/integration/test_live_mt5.py`** is the *only* place that
  imports the real `MetaTrader5` package. These tests are marked `live`, and
  skip cleanly when no terminal session is available.

A green run of the mock suite says nothing about connectivity. Only the `live`
tests do.

---

## How the tricky parts work

### Broker timestamps are not UTC

The MetaQuotes-Demo server used during development runs at **UTC+3**, so
treating its bar timestamps as UTC shifts every bar by three hours. The backend
measures the offset from the newest tick and caches it.

Crucially, the offset is only re-measured **while broker timestamps are still
advancing**. A frozen feed cannot be re-anchored to "now" and disguised as live
data. The offset is measured to the second rather than rounded to whole hours:
coarse rounding can shift a bar boundary by minutes, which is enough to
misclassify the newest closed M1 bar as still forming.

### Symbol discovery never silently picks the wrong instrument

Brokers name gold inconsistently. On one terminal the gold family is
`XAUUSD, XAUEUR, XAUAUD, XAUCHF, XAUGBP, XAUG` — so "find something with XAU in
it" would be dangerous. The rules are:

1. The exact configured `MT5_SYMBOL` always wins when the terminal has it.
2. Otherwise only **variants** of that symbol qualify — the base name plus a
   short broker modifier (`XAUUSDm`, `XAUUSD.a`, `#XAUUSD`). `XAUEUR` and `XAUG`
   are different instruments and are never selected.
3. `MT5_SYMBOL_CANDIDATES` is a **search hint, not a priority order**. It adds
   names to probe (only if the terminal really has them); it never breaks a tie.
4. Two equally plausible variants are reported as **ambiguous**. The dashboard
   shows the candidates and asks you to pin `MT5_SYMBOL` rather than guessing.

### Reconnection

Failed connects and dropped connections arm a capped exponential backoff with
jitter (2s doubling up to 60s). The retry timer is armed on *failure*, which is
what stops the monitor from re-running the whole initialization sequence on
every poll tick. Set `RECONNECT_MAX_ATTEMPTS` to a positive number to give up
after a budget instead of retrying forever.

### Never green without live data

The dashboard's status badge is derived from `data_status` **and** the tick's own
freshness, not from "the terminal is connected". A connected terminal with a
silent feed shows as **Stale data**, never as green. The same rule is enforced
in `/api/health`, which reports `degraded` whenever market data is not live.

---

## Troubleshooting

### The backend starts but reports `Disconnected` / `Terminal: Authorization failed`

The MetaTrader terminal is not running or not logged in. Open the terminal, log
into a demo account, wait for the connection status in the bottom-right corner
to go green, then restart the backend.

`MT5 initialize` error `-6 (Terminal: Authorization failed)` means exactly this.

### `-10001 IPC send failed`

The terminal is still starting. The backend retries automatically with backoff;
give it a few seconds. If it persists, restart the terminal.

### The backend connects to the wrong terminal

Several installs are present. Set an explicit path in `backend/.env`:

```
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
```

Discovery is logged at startup, listing every terminal it found.

### `Ambiguous symbol discovery for 'XAUUSD'`

The terminal offers two equally plausible variants (for example `XAUUSDm` and
`XAUUSDc`). That is intentionally refused rather than guessed. Set the exact name:

```
MT5_SYMBOL=XAUUSDm
```

`GET /api/market/symbols` lists the candidates.

### Dashboard says "Stale data" while prices look reasonable

The tick is older than `STALE_TICK_THRESHOLD_SECONDS`. Common causes: the market
is closed (XAUUSD trades Sunday evening to Friday evening, server time), the
terminal lost its server connection, or the symbol is not in Market Watch. The
panel shows the measured age and the last backend error.

### The chart is empty but the quote is live

Check `GET /api/market/candles?timeframe=M15&limit=10`. A `503` means the
terminal returned no history for that symbol/timeframe — usually a symbol that
is not selected in Market Watch. `CANDLE_REFRESH_SECONDS` controls how often
history is re-fetched.

### `ConfigurationError` at startup

The message names the failing field. The usual suspects:

- `MT5_TERMINAL_PATH` points at something that does not exist.
- `CANDLE_LIMIT` exceeds `MAX_CANDLE_LIMIT`.
- `RECONNECT_MAX_DELAY_SECONDS` is below `RECONNECT_INITIAL_DELAY_SECONDS`.
- `APP_READ_ONLY=false` — refused by design.

### Port 8000 (or 5173) is already in use

Change `BACKEND_PORT` in `backend/.env`, and the proxy target in
`frontend/vite.config.ts`.

### PowerShell refuses to run the scripts

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\<name>.ps1
```

### Where are the logs?

Logs go to the console in structured form. Set `LOG_FORMAT=json` for one JSON
object per line. `LOG_LEVEL=DEBUG` adds symbol discovery and candle-cache detail.
Credentials are redacted from every record.

---

## Project layout

```
fibonacci-mt5-bot/
├── backend/
│   ├── app/
│   │   ├── main.py                 FastAPI app factory, lifespan, CORS
│   │   ├── config.py               Validated settings + read-only guard
│   │   ├── logging_config.py       Structured logging + secret redaction
│   │   ├── errors.py               Consistent JSON error envelope
│   │   ├── storage.py              SQLite connection/market telemetry
│   │   ├── mt5/
│   │   │   ├── connection.py       Connection, discovery, backoff reconnect
│   │   │   ├── symbols.py          Broker symbol discovery + ambiguity handling
│   │   │   ├── market_data.py      Ticks, spreads, candles, broker clock
│   │   │   └── timeframes.py       The seven timeframes (single source of truth)
│   │   ├── api/
│   │   │   ├── deps.py             Shared FastAPI dependencies
│   │   │   ├── health.py           GET /api/health
│   │   │   ├── connection.py       GET /api/mt5/status, /api/mt5/events
│   │   │   ├── market_data.py      GET /api/market/*
│   │   │   └── websocket.py        WS  /ws/market
│   │   ├── schemas/                Pydantic response models
│   │   └── services/
│   │       └── market_monitor.py   The background monitoring loop
│   ├── tests/                      Mock-based tests
│   │   └── integration/            Genuine MT5 tests (marked "live")
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/             Connection, quote, timeframe, status cards
│   │   ├── pages/                  Dashboard container + pure presenter
│   │   ├── hooks/                  useMarketStream, useCandles
│   │   ├── services/               api, websocket, candle merge, state, format
│   │   ├── types/                  API contract types
│   │   ├── test/                   Fixtures and vitest setup
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts              Dev proxy + vitest config
├── scripts/                        setup_windows / start_backend / start_frontend / run_tests
├── .gitignore
└── README.md
```

---

## Phase boundaries

Phase 1 is infrastructure. The following are **deliberately absent** and are
enforced by `backend/tests/test_phase_boundaries.py`, which fails the build if
an order-execution function or a strategy identifier appears anywhere in
`backend/app/`:

- Order submission, modification or closure (`order_send`, `positions_close`, …)
- Fibonacci swing detection or retracement levels
- BUY / SELL / WAIT / NO TRADE signals
- Stop-loss, take-profit or lot sizing
- Position management, backtesting or strategy optimisation

The application also declares itself read-only in three places: `APP_READ_ONLY`
(configuration validation), `MT5Status.read_only` / `trading_enabled`
(every API response) and the dashboard banner.

---

## Handover to Phase 2

What Phase 2 can build on without rework:

- **A proven data path.** Live ticks and seven-timeframe OHLC flow from MT5
  through the backend to the browser, continuously and without page refreshes.
- **Correct time handling.** The broker clock offset is measured, cached, drift-
  aware and exposed. Fibonacci levels computed against `open_time_utc` will land
  on the right bars.
- **A trustworthy candle source.** `latest_closed_candle` is reliable even on
  M1, which is the bar boundary a swing detector depends on.
- **A delivery mechanism.** `MarketMonitor` already fans snapshots out to
  subscribers with backpressure, and `GET /api/market/candles` already serves
  history for any of the seven timeframes. Strategy output can be added as a new
  field on the snapshot and a new router — no restructuring needed.
- **Safe failure behaviour.** Disconnects, stale feeds and ambiguous symbols are
  represented as explicit states rather than crashes or silent wrong data.

Deliberately left open for Phase 2 to decide: where strategy state lives, how
signals are persisted, and whether signal computation runs inside the monitor
loop or as a separate consumer of its snapshots.
