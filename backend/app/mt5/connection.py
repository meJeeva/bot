"""MetaTrader 5 connection manager.

Design notes
------------
* **Read-only.** This module never imports or calls an order-execution
  function. The only MetaTrader functions used are ``initialize``, ``shutdown``,
  ``terminal_info``, ``account_info``,
  ``version``, ``last_error``, ``symbol_info``, ``symbol_info_tick``,
  ``symbol_select``, ``symbols_get``, ``symbols_total`` and
  ``copy_rates_from_pos``.
* **Thread-safe.** The MetaTrader5 Python package marshals calls over a single
  IPC channel and is not thread-safe. Every call is therefore funnelled through
  one worker thread guarded by a re-entrant lock, which also keeps long
  blocking calls off the FastAPI event loop.
* **No hard-coded credentials.** An already-authenticated terminal session is
  the preferred mode; optional credentials come from environment configuration
  and are never logged or exposed through the API.
* **Terminal discovery.** ``MT5_TERMINAL_PATH`` wins when set. Otherwise the
  terminal directories recorded by MetaQuotes and the usual install roots are
  scanned, then ``mt5.initialize()`` is given a chance to attach to a running
  terminal.
"""

from __future__ import annotations

import asyncio
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from ..config import Settings
from ..logging_config import get_logger
from ..schemas.status import AccountType, ConnectionState, MT5Status

logger = get_logger(__name__)

T = TypeVar("T")

TERMINAL_EXECUTABLE = "terminal64.exe"

# Coarse MT5 return codes worth surfacing verbatim.
_MT5_ERROR_HINTS: dict[int, str] = {
    -1: "Unexpected internal error inside the MetaTrader5 package.",
    -2: "Invalid arguments passed to a MetaTrader 5 function.",
    -3: "The MetaTrader 5 terminal is not running.",
    -4: "MetaTrader 5 initialize() has not been called or failed.",
    -5: "The MetaTrader 5 terminal has not been authorized yet. Log the "
        "terminal into a demo or live account first.",
    -6: "Terminal authorization failed. Open the terminal and log in.",
    -7: "The requested terminal build is out of date.",
    -8: "Explicitly provided credentials were rejected by the trading server.",
    -10001: "IPC send failed. The terminal is still starting - retry shortly.",
    -10002: "IPC timeout communicating with the terminal.",
    -10003: "The terminal was closed during the operation.",
}


class MT5UnavailableError(RuntimeError):
    """The MetaTrader5 package could not be used at all."""


class MT5ConnectionError(RuntimeError):
    """A connection attempt to the terminal failed."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        self.code = code
        super().__init__(message)


def _import_mt5() -> Any:
    try:
        import MetaTrader5 as mt5  # noqa: PLC0415 - imported lazily on purpose
    except Exception as exc:  # pragma: no cover - environment dependent
        raise MT5UnavailableError(
            "The MetaTrader5 Python package is not installed. Run "
            "scripts/setup_windows.ps1 (or "
            "'pip install -r backend/requirements.txt') inside the virtual "
            "environment and restart the backend."
        ) from exc
    return mt5


def describe_mt5_error(error: Any) -> str:
    """Turn an ``mt5.last_error()`` tuple into an actionable message."""
    if isinstance(error, tuple) and len(error) == 2:
        code, text = error
        hint = _MT5_ERROR_HINTS.get(int(code))
        return f"{code} ({text})" + (f" - {hint}" if hint else "")
    return str(error)


def discover_terminal_paths() -> list[str]:
    """Best-effort discovery of installed MetaTrader 5 terminal executables.

    Sources, in priority order:

    1. ``%APPDATA%/MetaQuotes/Terminal/<instance>/origin.txt`` - written by the
       terminal itself and points at its install directory.
    2. The usual Windows install roots, scanned one and two levels deep.

    Returns absolute paths to ``terminal64.exe`` files, de-duplicated.
    """
    found: list[str] = []

    def _add(path: Path) -> None:
        try:
            resolved = str(path.resolve())
        except OSError:  # pragma: no cover - defensive
            return
        if resolved not in found and path.is_file():
            found.append(resolved)

    appdata = os.environ.get("APPDATA")
    if appdata:
        terminals_root = Path(appdata) / "MetaQuotes" / "Terminal"
        if terminals_root.is_dir():
            for instance in sorted(terminals_root.iterdir()):
                origin = instance / "origin.txt"
                if not origin.is_file():
                    continue
                try:
                    install_dir = Path(origin.read_text(encoding="utf-16").strip())
                except UnicodeError:
                    try:
                        install_dir = Path(origin.read_text(encoding="utf-8").strip())
                    except OSError:  # pragma: no cover - defensive
                        continue
                except OSError:  # pragma: no cover - defensive
                    continue
                if install_dir.is_dir():
                    _add(install_dir / TERMINAL_EXECUTABLE)

    roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramW6432"),
        os.environ.get("LOCALAPPDATA") and str(Path(os.environ["LOCALAPPDATA"]) / "Programs"),
    ]

    for root in roots:
        if not root:
            continue
        root_path = Path(root)
        if not root_path.is_dir():
            continue

        _add(root_path / "MetaTrader 5" / TERMINAL_EXECUTABLE)
        try:
            children = sorted(root_path.iterdir())
        except OSError:  # pragma: no cover - defensive
            continue
        for child in children:
            if not child.is_dir():
                continue
            _add(child / TERMINAL_EXECUTABLE)

    return found


class MT5Connection:
    """Owns the lifecycle of the MetaTrader 5 terminal connection."""

    def __init__(self, settings: Settings, *, mt5_module: Any | None = None) -> None:
        self._settings = settings
        self._mt5 = mt5_module
        self._mt5_import_attempted = mt5_module is not None

        self._lock = threading.RLock()
        # A single worker serialises every MetaTrader call: the package is not
        # thread-safe, and this also keeps blocking IPC off the event loop.
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mt5-ipc"
        )

        self._initialized = False
        self._terminal_path: str | None = None
        self._last_connected_at: datetime | None = None
        self._last_connection_error: str | None = None
        self._last_market_data_at: datetime | None = None
        self._reconnect_attempts = 0
        self._next_reconnect_at: datetime | None = None
        self._state: ConnectionState = ConnectionState.DISCONNECTED
        self._closed = False
        self._executor_shutdown = False
        # Terminal discovery touches the filesystem; cache it per process.
        self._discovered_paths: list[str] | None = None

    # ------------------------------------------------------------------
    # Module access
    # ------------------------------------------------------------------
    @property
    def mt5(self) -> Any:
        """The MetaTrader5 module handle (imported lazily, once)."""
        if self._mt5 is None:
            if self._mt5_import_attempted:
                raise MT5UnavailableError(
                    "The MetaTrader5 package is not available in this process."
                )
            self._mt5 = _import_mt5()
            self._mt5_import_attempted = True
        return self._mt5

    @property
    def settings(self) -> Settings:
        return self._settings

    # ------------------------------------------------------------------
    # Serialised execution
    # ------------------------------------------------------------------
    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a MetaTrader call synchronously under the connection lock.

        A single positional argument is passed *directly* rather than through
        ``*args`` unpacking. The compiled MetaTrader5 functions behave
        differently in the two cases: when the request mapping arrives
        unpacked, the terminal rejects it with retcode -2 ("Unnamed
        arguments not allowed"), which would turn every order request into an
        uncertain outcome. This was found against a real terminal (the XM
        Global demo account) and only shows up there - a Python fake cannot
        see the difference.
        """
        with self._lock:
            if not kwargs and len(args) == 1:
                return func(args[0])
            return func(*args, **kwargs)

    async def acall(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a MetaTrader call off the event loop, still serialised."""
        loop = asyncio.get_running_loop()

        def _runner() -> T:
            return self.call(func, *args, **kwargs)

        return await loop.run_in_executor(self._executor, _runner)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def initialize_sync(self) -> bool:
        """Initialize the terminal connection. Returns ``True`` on success."""
        with self._lock:
            if self._closed:
                raise MT5ConnectionError("Connection has already been shut down.")

            if self._initialized and self._is_terminal_connected():
                return True

            self._state = ConnectionState.CONNECTING
            try:
                mt5 = self.mt5
            except MT5UnavailableError as exc:
                # The MetaTrader5 package itself cannot be used. Record the
                # reason so the status endpoint (and the UI) reports it,
                # instead of leaving the connection "connecting" forever and
                # raising on every poll.
                self._register_failure(str(exc))
                return False

            attempts = self._initialization_candidates()
            last_error_text = "no terminal candidate available"

            for label, kwargs in attempts:
                try:
                    logger.info("MT5 initialize attempt: %s", label)
                    ok = mt5.initialize(**kwargs)
                except Exception as exc:  # pragma: no cover - defensive
                    last_error_text = f"{label}: {exc}"
                    logger.error("MT5 initialize raised for %s: %s", label, exc)
                    continue

                if ok:
                    self._initialized = True
                    self._terminal_path = (
                        kwargs.get("path") or self._read_terminal_path() or None
                    )
                    logger.info("MT5 connected via %s (path=%s)", label, self._terminal_path)
                    break

                last_error_text = describe_mt5_error(self._safe_last_error())
                logger.warning("MT5 initialize failed for %s: %s", label, last_error_text)
                try:
                    mt5.shutdown()
                except Exception:  # pragma: no cover - defensive
                    pass

            if not self._initialized:
                self._register_failure(f"MT5 initialization failed: {last_error_text}")
                return False

            if not self._is_terminal_connected():
                self._register_failure(
                    "MT5 initialized but the terminal is not connected to its "
                    "trading server. Check the terminal's connection status."
                )
                return False

            if not self._read_account_info():
                self._register_failure(
                    "MT5 initialized but no account information is available. "
                    "Log the terminal into a demo or live account."
                )
                return False

            self._state = ConnectionState.CONNECTED
            self._last_connected_at = datetime.now(timezone.utc)
            self._last_connection_error = None
            self._reconnect_attempts = 0
            self._next_reconnect_at = None
            logger.info("MT5 connection established successfully.")
            return True

    async def initialize(self) -> bool:
        """Async wrapper around :meth:`initialize_sync`."""
        return await self.acall(self.initialize_sync)

    def shutdown_sync(self) -> None:
        """Release the terminal connection. Safe to call repeatedly."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._initialized:
                try:
                    self.mt5.shutdown()
                    logger.info("MT5 connection shut down cleanly.")
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Error during MT5 shutdown: %s", exc)
            self._initialized = False
            self._state = ConnectionState.DISCONNECTED

    async def shutdown(self) -> None:
        """Release the connection and the worker thread. Idempotent."""
        if self._executor_shutdown:
            return
        try:
            if not self._closed:
                await self.acall(self.shutdown_sync)
        finally:
            self._executor_shutdown = True
            self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    # Detecting and recovering from disconnects
    # ------------------------------------------------------------------
    def is_connected(self) -> bool:
        """``True`` when the terminal is initialized and connected."""
        with self._lock:
            if not self._initialized:
                return False
            return self._is_terminal_connected()

    def next_reconnect_delay(self) -> float:
        """Capped exponential backoff with jitter.

        Prevents the rapid, unlimited reconnect loops that would hammer the
        terminal and saturate the CPU.
        """
        base = self._settings.reconnect_initial_delay_seconds
        maximum = self._settings.reconnect_max_delay_seconds
        exponent = max(0, min(self._reconnect_attempts, 16))
        delay = min(base * (2**exponent), maximum)
        jitter = random.uniform(0, min(1.0, delay * 0.1))
        return min(delay + jitter, maximum)

    def register_disconnect(self, error: str) -> None:
        """Record a lost connection and schedule the next retry."""
        with self._lock:
            self._initialized = False
            delay = self._schedule_retry()
            self._last_connection_error = error
            self._state = ConnectionState.RECONNECTING
            logger.warning(
                "MT5 disconnected: %s. Reconnect attempt %s scheduled in %.1fs.",
                error,
                self._reconnect_attempts,
                delay,
            )

    def reconnect_sync(self) -> bool:
        """Attempt a controlled reconnect, honouring the backoff schedule."""
        with self._lock:
            if self._closed:
                return False

            # The attempt limit outranks the backoff timer: once the budget is
            # spent the connection must stop retrying, whatever the clock says.
            limit = self._settings.reconnect_max_attempts
            if limit and self._reconnect_attempts >= limit:
                self._state = ConnectionState.ERROR
                self._last_connection_error = (
                    f"Giving up after {self._reconnect_attempts} reconnect "
                    "attempts. Check the MetaTrader terminal and restart the "
                    "backend when it is available."
                )
                logger.error("%s", self._last_connection_error)
                return False

            now = datetime.now(timezone.utc)
            if self._next_reconnect_at and now < self._next_reconnect_at:
                return False

            try:
                self.mt5.shutdown()
            except Exception:  # pragma: no cover - defensive
                pass
            self._initialized = False

            logger.info(
                "Attempting MT5 reconnect (attempt %s)", self._reconnect_attempts + 1
            )
            return self.initialize_sync()

    def _schedule_retry(self) -> float:
        """Arm the backoff timer. Caller must hold the lock."""
        delay = self.next_reconnect_delay()
        self._reconnect_attempts += 1
        self._next_reconnect_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        return delay

    def _register_failure(self, message: str) -> None:
        """Record a failed connect attempt *and* arm the backoff timer.

        Arming the timer here is what stops the monitor from re-running the
        whole initialization sequence on every poll tick.
        """
        self._state = ConnectionState.ERROR
        self._last_connection_error = message
        self._initialized = False
        delay = self._schedule_retry()
        logger.error("%s Next reconnect attempt in %.1fs.", message, delay)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def mark_market_data(self, when: datetime | None = None) -> None:
        """Record a successful market-data read."""
        with self._lock:
            self._last_market_data_at = when or datetime.now(timezone.utc)

    def build_status_sync(self) -> MT5Status:
        """Build a safe status object. Never includes secrets."""
        with self._lock:
            terminal = self._safe_terminal_info()
            account = self._safe_account_info()

            terminal_connected = bool(terminal and getattr(terminal, "connected", False))

            if self._initialized and terminal_connected:
                state = ConnectionState.CONNECTED
            elif self._state is ConnectionState.ERROR:
                state = ConnectionState.ERROR
            elif self._reconnect_attempts and self._initialized is False:
                state = ConnectionState.RECONNECTING
            elif self._state is ConnectionState.CONNECTING:
                state = ConnectionState.CONNECTING
            else:
                state = ConnectionState.DISCONNECTED

            if terminal_connected and self._initialized:
                self._state = ConnectionState.CONNECTED

            version = None
            if self._initialized:
                try:
                    version = self.mt5.version()
                except Exception:  # pragma: no cover - defensive
                    version = None

            login = getattr(account, "login", None) if account else None
            trade_mode = getattr(account, "trade_mode", None) if account else None

            masked = mask_login(login) if login is not None else None
            expose = self._settings.expose_account_login

            return MT5Status(
                state=state,
                mt5_initialized=self._initialized,
                terminal_connected=terminal_connected,
                terminal_path=self._terminal_path
                or (getattr(terminal, "path", None) if terminal else None),
                terminal_name=getattr(terminal, "name", None) if terminal else None,
                terminal_company=getattr(terminal, "company", None) if terminal else None,
                terminal_build=getattr(terminal, "build", None) if terminal else None,
                terminal_language=getattr(terminal, "language", None) if terminal else None,
                trading_server=(
                    getattr(account, "server", None) if account else None
                )
                or (getattr(terminal, "server", None) if terminal else None),
                account_login_masked=masked,
                account_login=int(login) if (login is not None and expose) else None,
                account_currency=getattr(account, "currency", None) if account else None,
                account_type=classify_account(trade_mode),
                account_trade_mode=int(trade_mode) if trade_mode is not None else None,
                last_connected_at=self._last_connected_at,
                last_connection_error=self._last_connection_error,
                last_market_data_at=self._last_market_data_at,
                reconnecting=state is ConnectionState.RECONNECTING,
                reconnect_attempts=self._reconnect_attempts,
                next_reconnect_at=self._next_reconnect_at,
                trading_enabled=False,
                read_only=True,
                timestamp=datetime.now(timezone.utc),
            )

    async def build_status(self) -> MT5Status:
        return await self.acall(self.build_status_sync)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _initialization_candidates(self) -> list[tuple[str, dict[str, Any]]]:
        """Ordered ``(label, initialize-kwargs)`` pairs to try.

        Ordering matters. Attaching to a terminal that is already running and
        authenticated is the preferred mode, so it is attempted *before*
        launching a discovered install (which would come up at a login prompt
        and cannot serve data). An explicitly configured path always wins.
        """
        settings = self._settings
        candidates: list[tuple[str, dict[str, Any]]] = []

        credential_kwargs: dict[str, Any] = {}
        if settings.mt5_login is not None:
            credential_kwargs["login"] = settings.mt5_login
            if settings.mt5_password:
                credential_kwargs["password"] = settings.mt5_password
            if settings.mt5_server:
                credential_kwargs["server"] = settings.mt5_server
        # Always bound the IPC handshake so one bad candidate cannot hang.
        credential_kwargs["timeout"] = settings.mt5_timeout_ms

        if settings.mt5_terminal_path:
            path = Path(settings.mt5_terminal_path)
            executable = path / TERMINAL_EXECUTABLE if path.is_dir() else path
            candidates.append(
                (
                    f"configured terminal {executable}",
                    {"path": str(executable), **credential_kwargs},
                )
            )

        # Preferred: attach to the terminal the user already has open.
        candidates.append(("auto-attach to running terminal", dict(credential_kwargs)))

        if self._discovered_paths is None:
            self._discovered_paths = discover_terminal_paths()
            if self._discovered_paths:
                logger.info(
                    "Discovered %s MetaTrader 5 terminal(s): %s",
                    len(self._discovered_paths),
                    ", ".join(self._discovered_paths),
                )

        for discovered in self._discovered_paths:
            candidates.append(
                (
                    f"discovered terminal {discovered}",
                    {"path": discovered, **credential_kwargs},
                )
            )

        return candidates

    def _read_terminal_path(self) -> str | None:
        terminal = self._safe_terminal_info()
        return getattr(terminal, "path", None) if terminal else None

    def _safe_terminal_info(self) -> Any:
        try:
            return self.mt5.terminal_info()
        except Exception:  # pragma: no cover - defensive
            return None

    def _safe_account_info(self) -> Any:
        try:
            return self.mt5.account_info()
        except Exception:  # pragma: no cover - defensive
            return None

    def _is_terminal_connected(self) -> bool:
        if not self._initialized:
            return False
        terminal = self._safe_terminal_info()
        return bool(terminal and getattr(terminal, "connected", False))

    def _read_account_info(self) -> bool:
        return self._safe_account_info() is not None

    def _safe_last_error(self) -> Any:
        try:
            return self.mt5.last_error()
        except Exception:  # pragma: no cover - defensive
            return None


def mask_login(login: Any) -> str | None:
    """Mask an account login, keeping at most the last four digits."""
    if login is None:
        return None
    text = str(login).strip()
    if not text:
        return None
    if len(text) <= 4:
        return "*" * len(text)
    return "*" * (len(text) - 4) + text[-4:]


def classify_account(trade_mode: Any) -> AccountType:
    """Map ``account_info().trade_mode`` onto demo/live.

    MetaTrader constants: 0 = demo, 1 = contest, 2 = real.
    """
    if trade_mode is None:
        return AccountType.UNKNOWN
    try:
        mode = int(trade_mode)
    except (TypeError, ValueError):
        return AccountType.UNKNOWN
    if mode == 0:
        return AccountType.DEMO
    if mode == 2:
        return AccountType.LIVE
    return AccountType.UNKNOWN
