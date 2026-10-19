"""SQLite status persistence.

The store is optional infrastructure, so the important behaviour is that it
records what it can and never takes the monitor down when it cannot.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.market import Quote
from app.schemas.status import AccountType, ConnectionState, MT5Status
from app.storage import StatusStore


def make_status(**overrides) -> MT5Status:
    base = dict(
        state=ConnectionState.CONNECTED,
        mt5_initialized=True,
        terminal_connected=True,
        account_type=AccountType.DEMO,
        last_connection_error=None,
    )
    base.update(overrides)
    return MT5Status(**base)


def make_quote(**overrides) -> Quote:
    base = dict(
        symbol="XAUUSD",
        bid=2400.0,
        ask=2400.5,
        spread_price=0.5,
        spread_points=50.0,
        point=0.01,
        digits=2,
        freshness="live",
        age_seconds=0.2,
        received_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return Quote(**base)


class TestStatusStore:
    def test_creates_the_database_and_schema(self, tmp_path):
        store = StatusStore(tmp_path / "nested" / "status.db")
        assert store.initialize() is True
        assert store.enabled is True
        assert (tmp_path / "nested" / "status.db").exists()
        store.close()

    def test_records_and_reads_back_a_connection_event(self, tmp_path):
        store = StatusStore(tmp_path / "status.db")
        store.initialize()

        assert store.record_connection_event(make_status(), symbol="XAUUSD") is True

        events = store.recent_connection_events()
        assert len(events) == 1
        assert events[0]["state"] == "connected"
        assert events[0]["connected"] is True
        assert events[0]["symbol"] == "XAUUSD"
        store.close()

    def test_identical_connection_states_are_deduplicated(self, tmp_path):
        store = StatusStore(tmp_path / "status.db")
        store.initialize()

        assert store.record_connection_event(make_status()) is True
        assert store.record_connection_event(make_status()) is False
        assert store.counts()[0] == 1

        store.record_connection_event(make_status(terminal_connected=False))
        assert store.counts()[0] == 2
        store.close()

    def test_records_quotes(self, tmp_path):
        store = StatusStore(tmp_path / "status.db")
        store.initialize()

        assert store.record_quote(make_quote()) is True
        assert store.record_quote(
            make_quote(bid=2400.1, ask=2400.6, spread_price=0.5, age_seconds=0.5)
        ) is True

        events, snapshots = store.counts()
        assert snapshots == 2
        store.close()

    def test_recent_errors_only_returns_failures(self, tmp_path):
        store = StatusStore(tmp_path / "status.db")
        store.initialize()

        store.record_connection_event(make_status())
        store.record_connection_event(
            make_status(state=ConnectionState.ERROR, last_connection_error="boom")
        )

        errors = store.recent_errors()
        assert len(errors) == 1
        assert errors[0]["error"] == "boom"
        store.close()

    def test_stats_reports_counts_and_path(self, tmp_path):
        path = tmp_path / "status.db"
        store = StatusStore(path)
        store.initialize()
        store.record_connection_event(make_status())

        stats = store.stats()
        assert stats.enabled is True
        assert stats.connection_events == 1
        assert stats.path == str(path)
        store.close()

    def test_disabled_store_is_a_no_op(self, tmp_path):
        store = StatusStore(tmp_path / "status.db", enabled=False)

        assert store.initialize() is False
        assert store.enabled is False
        assert store.record_connection_event(make_status()) is False
        assert store.record_quote(make_quote()) is False
        assert store.recent_connection_events() == []
        assert store.counts() == (0, 0)

    def test_unwritable_location_does_not_raise(self, tmp_path):
        # A directory where the database file should be: sqlite cannot open it.
        blocked = tmp_path / "blocked"
        blocked.mkdir()

        store = StatusStore(blocked)
        assert store.initialize() is False
        assert store.enabled is False

    def test_close_is_idempotent(self, tmp_path):
        store = StatusStore(tmp_path / "status.db")
        store.initialize()
        store.close()
        store.close()
        assert store.recent_connection_events() == []

    def test_survives_a_reopen(self, tmp_path):
        path = tmp_path / "status.db"
        first = StatusStore(path)
        first.initialize()
        first.record_connection_event(make_status())
        first.close()

        second = StatusStore(path)
        second.initialize()
        assert len(second.recent_connection_events()) == 1
        second.close()

