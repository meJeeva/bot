"""MT5 connection manager behaviour.

Covers successful initialization, failed initialization, controlled
reconnection with capped backoff, terminal discovery and credential hygiene.
No real terminal is involved - :class:`tests.fakes.FakeMT5` stands in.
"""

from __future__ import annotations

import dis
import sys
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.mt5.connection import (
    MT5Connection,
    MT5UnavailableError,
    classify_account,
    describe_mt5_error,
    discover_terminal_paths,
    mask_login,
)
from app.schemas.status import AccountType, ConnectionState
from tests.fakes import (
    ACCOUNT_TRADE_MODE_CONTEST,
    ACCOUNT_TRADE_MODE_DEMO,
    ACCOUNT_TRADE_MODE_REAL,
    FakeAccountInfo,
    FakeMT5,
    FakeTerminalInfo,
)


def build(**overrides) -> Settings:
    overrides.setdefault("database_enabled", False)
    overrides.setdefault("log_level", "WARNING")
    return Settings(_env_file=None, **overrides)


@pytest.fixture(autouse=True)
def no_terminal_discovery(monkeypatch):
    """Keep candidate lists deterministic; discovery is tested on its own."""
    monkeypatch.setattr("app.mt5.connection.discover_terminal_paths", lambda: [])


class TestInitialization:
    async def test_successful_initialization(self, fake_mt5):
        connection = MT5Connection(build(), mt5_module=fake_mt5)

        assert await connection.initialize() is True
        assert connection.is_connected() is True

        status = connection.build_status_sync()
        assert status.state is ConnectionState.CONNECTED
        assert status.mt5_initialized is True
        assert status.terminal_connected is True
        assert status.trading_server == "MetaQuotes-Demo"
        assert status.account_currency == "USD"
        assert status.account_type is AccountType.DEMO
        assert status.last_connected_at is not None
        assert status.last_connection_error is None
        assert status.read_only is True
        assert status.trading_enabled is False

    async def test_failed_initialization_reports_instead_of_raising(self):
        fake = FakeMT5(initialize_ok=False, last_error_value=(-6, "Terminal: Authorization failed"))
        connection = MT5Connection(build(), mt5_module=fake)

        assert await connection.initialize() is False
        assert connection.is_connected() is False

        status = connection.build_status_sync()
        assert status.state is ConnectionState.ERROR
        assert status.mt5_initialized is False
        assert status.last_connection_error is not None
        assert "Authorization failed" in status.last_connection_error

    async def test_a_missing_metatrader5_package_is_reported_not_raised(self, monkeypatch):
        """A machine without the MetaTrader5 package must fail honestly.

        The reason has to reach the status payload (and therefore the UI) so
        the operator can see *why* the terminal is unavailable.
        """

        def _unavailable():
            raise MT5UnavailableError(
                "The MetaTrader5 Python package is not installed."
            )

        monkeypatch.setattr("app.mt5.connection._import_mt5", _unavailable)
        connection = MT5Connection(build())  # no module override: the real import is used

        assert await connection.initialize() is False
        assert connection.is_connected() is False

        status = connection.build_status_sync()
        assert status.state is ConnectionState.ERROR
        assert status.mt5_initialized is False
        assert "not installed" in (status.last_connection_error or "")

        # A later retry must not raise either: the failure is recorded, not thrown.
        await connection.acall(lambda: (_sleep_backoff(connection)))
        assert await connection.acall(connection.reconnect_sync) is False
        assert connection.build_status_sync().state is ConnectionState.ERROR

    async def test_terminal_that_is_not_connected_to_its_server_is_rejected(self):
        fake = FakeMT5(terminal=FakeTerminalInfo(connected=False))
        connection = MT5Connection(build(), mt5_module=fake)

        assert await connection.initialize() is False
        status = connection.build_status_sync()
        assert status.last_connection_error is not None
        assert "not connected to its trading server" in status.last_connection_error

    async def test_initialization_without_account_information_is_rejected(self):
        class NoAccountMT5(FakeMT5):
            def account_info(self):  # noqa: D102
                self._record("account_info")
                return None

        connection = MT5Connection(build(), mt5_module=NoAccountMT5())
        assert await connection.initialize() is False
        assert "no account information" in (connection.build_status_sync().last_connection_error or "")

    async def test_configured_terminal_path_is_tried_first(self, tmp_path):
        executable = tmp_path / "terminal64.exe"
        executable.write_text("stub", encoding="utf-8")

        fake = FakeMT5()
        connection = MT5Connection(
            build(mt5_terminal_path=str(executable)), mt5_module=fake
        )
        assert await connection.initialize() is True

        first = next(call for call in fake.calls if call[0] == "initialize")
        assert first[2]["path"] == str(executable)

    async def test_shutdown_is_clean_and_idempotent(self, fake_mt5):
        connection = MT5Connection(build(), mt5_module=fake_mt5)
        await connection.initialize()

        await connection.shutdown()
        assert fake_mt5.shutdown_calls == 1

        await connection.shutdown()
        assert fake_mt5.shutdown_calls == 1


class TestReconnection:
    async def test_failed_connect_schedules_a_delayed_retry(self):
        fake = FakeMT5(initialize_ok=False)
        connection = MT5Connection(build(reconnect_initial_delay_seconds=5), mt5_module=fake)

        await connection.initialize()

        status = connection.build_status_sync()
        assert status.next_reconnect_at is not None
        assert status.reconnect_attempts == 1

        # A retry before the delay elapses is refused, so the loop cannot spin.
        calls_before = len([c for c in fake.calls if c[0] == "initialize"])
        assert await connection.acall(connection.reconnect_sync) is False
        calls_after = len([c for c in fake.calls if c[0] == "initialize"])
        assert calls_after == calls_before

    async def test_reconnect_succeeds_when_the_terminal_returns(self):
        fake = FakeMT5(initialize_ok=False)
        connection = MT5Connection(build(reconnect_initial_delay_seconds=0.01), mt5_module=fake)
        await connection.initialize()
        assert connection.is_connected() is False

        fake.initialize_ok = True
        await connection.acall(lambda: (_sleep_backoff(connection)))
        assert await connection.acall(connection.reconnect_sync) is True

        status = connection.build_status_sync()
        assert status.state is ConnectionState.CONNECTED
        assert status.reconnect_attempts == 0

    async def test_backoff_grows_and_is_capped(self):
        settings = build(
            reconnect_initial_delay_seconds=2,
            reconnect_max_delay_seconds=16,
            reconnect_max_attempts=0,
        )
        connection = MT5Connection(settings, mt5_module=FakeMT5(initialize_ok=False))

        delays = []
        for _ in range(10):
            connection._reconnect_attempts = len(delays)
            delays.append(connection.next_reconnect_delay())

        assert delays[0] < delays[1] < delays[2]
        assert max(delays) <= 16 * 1.1  # cap plus the small jitter

    async def test_gives_up_after_the_configured_attempt_limit(self):
        fake = FakeMT5(
            initialize_ok=False,
            last_error_value=(-6, "Terminal: Authorization failed"),
        )
        connection = MT5Connection(
            build(reconnect_initial_delay_seconds=0.01, reconnect_max_attempts=1),
            mt5_module=fake,
        )
        await connection.initialize()  # attempts == 1

        assert await connection.acall(connection.reconnect_sync) is False
        status = connection.build_status_sync()
        assert status.state is ConnectionState.ERROR
        assert "Giving up" in (status.last_connection_error or "")

    async def test_register_disconnect_marks_reconnecting(self):
        connection = MT5Connection(build(), mt5_module=FakeMT5())
        await connection.initialize()

        connection.register_disconnect("Terminal closed unexpectedly")

        status = connection.build_status_sync()
        assert status.reconnecting is True
        assert status.state is ConnectionState.RECONNECTING
        assert status.reconnect_attempts == 1


def _sleep_backoff(connection: MT5Connection) -> None:
    """Wait out the (tiny) backoff window inside the worker thread."""
    connection._next_reconnect_at = datetime.now(timezone.utc) - timedelta(seconds=1)


class TestTerminalDiscovery:
    def test_discovers_from_the_metatrader_instance_directory(self, tmp_path, monkeypatch):
        install = tmp_path / "CustomMT5"
        install.mkdir()
        (install / "terminal64.exe").write_text("stub", encoding="utf-8")

        instance = tmp_path / "appdata" / "MetaQuotes" / "Terminal" / "ABCDEF"
        instance.mkdir(parents=True)
        (instance / "origin.txt").write_text(str(install), encoding="utf-16")

        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
        monkeypatch.setenv("ProgramFiles", str(tmp_path / "nonexistent"))
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        monkeypatch.delenv("ProgramW6432", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)

        discovered = discover_terminal_paths()
        assert str((install / "terminal64.exe").resolve()) in discovered

    def test_discovers_from_program_files(self, tmp_path, monkeypatch):
        install = tmp_path / "Program Files" / "MetaTrader 5"
        install.mkdir(parents=True)
        (install / "terminal64.exe").write_text("stub", encoding="utf-8")

        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
        monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        monkeypatch.delenv("ProgramW6432", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)

        discovered = discover_terminal_paths()
        assert str((install / "terminal64.exe").resolve()) in discovered

    def test_returns_empty_when_nothing_is_installed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
        monkeypatch.setenv("ProgramFiles", str(tmp_path / "empty"))
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        monkeypatch.delenv("ProgramW6432", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)

        assert discover_terminal_paths() == []


class TestAccountClassification:
    @pytest.mark.parametrize(
        "mode,expected",
        [
            (ACCOUNT_TRADE_MODE_DEMO, AccountType.DEMO),
            (ACCOUNT_TRADE_MODE_CONTEST, AccountType.UNKNOWN),
            (ACCOUNT_TRADE_MODE_REAL, AccountType.LIVE),
            (None, AccountType.UNKNOWN),
            ("nonsense", AccountType.UNKNOWN),
        ],
    )
    def test_maps_trade_mode(self, mode, expected):
        assert classify_account(mode) is expected

    def test_real_account_is_reported_as_live(self):
        fake = FakeMT5(account=FakeAccountInfo(trade_mode=ACCOUNT_TRADE_MODE_REAL))
        connection = MT5Connection(build(), mt5_module=fake)
        assert connection.initialize_sync() is True
        assert connection.build_status_sync().account_type is AccountType.LIVE


class TestCallConvention:
    """The compiled MetaTrader5 functions need their argument passed directly.

    When a request mapping reaches the compiled function through ``*args``
    unpacking, the terminal rejects it with retcode -2 ("Unnamed arguments
    not allowed"). A Python fake cannot see the difference - it was found
    against a real terminal - so the calling convention itself is asserted
    here.
    """

    @staticmethod
    def _caller_opcode(function):
        """The bytecode opcode used to call *function*."""
        seen: list[str] = []

        def tracer(frame, event, arg):  # pragma: no cover - traced frames
            if event == "call":
                caller = frame.f_back
                if caller is not None:
                    opcode = None
                    for instruction in dis.get_instructions(caller.f_code):
                        if instruction.offset <= caller.f_lasti:
                            opcode = instruction.opname
                    seen.append(opcode or "")
            return tracer

        def target(*args, **kwargs):
            return args, kwargs

        sys.settrace(tracer)
        try:
            function(target, {"action": 1})
        finally:
            sys.settrace(None)
        assert seen, "the call was not observed"
        return seen[-1]

    def test_a_single_mapping_argument_is_passed_directly(self):
        connection = MT5Connection(build(), mt5_module=FakeMT5())
        opcode = self._caller_opcode(connection.call)
        assert opcode == "CALL"
        assert opcode != "CALL_FUNCTION_EX"

    def test_several_arguments_keep_the_ordinary_call(self):
        connection = MT5Connection(build(), mt5_module=FakeMT5())
        captured: dict[str, object] = {}

        def target(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return args, kwargs

        connection.call(target, 1, 2)
        assert captured["args"] == (1, 2)
        assert captured["kwargs"] == {}


class TestCredentialHygiene:
    @pytest.mark.parametrize(
        "login,expected",
        [
            (5057247615, "******7615"),
            (1234, "****"),
            (None, None),
            ("", None),
        ],
    )
    def test_login_masking(self, login, expected):
        assert mask_login(login) == expected

    def test_status_masks_the_login_by_default(self):
        connection = MT5Connection(build(), mt5_module=FakeMT5())
        connection.initialize_sync()

        status = connection.build_status_sync()
        assert status.account_login_masked == "******7615"
        assert status.account_login is None

    def test_login_can_be_exposed_explicitly(self):
        connection = MT5Connection(
            build(expose_account_login=True), mt5_module=FakeMT5()
        )
        connection.initialize_sync()
        assert connection.build_status_sync().account_login == 5057247615

    def test_status_never_contains_a_password(self):
        connection = MT5Connection(
            build(
                mt5_login=5057247615,
                mt5_password="hunter2",
                mt5_server="MetaQuotes-Demo",
            ),
            mt5_module=FakeMT5(),
        )
        connection.initialize_sync()

        rendered = connection.build_status_sync().model_dump_json()
        assert "hunter2" not in rendered

    def test_error_messages_are_actionable(self):
        assert "log in" in describe_mt5_error((-6, "Terminal: Authorization failed")).lower()
        assert "not running" in describe_mt5_error((-3, "Terminal: not found")).lower()
        assert describe_mt5_error(("weird",)) == "('weird',)"
