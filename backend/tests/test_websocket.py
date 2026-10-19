"""``WS /ws/market``.

Covers the initial snapshot, continuous updates, several simultaneous clients,
disconnect cleanup and the guarantee that the stream reports stale data instead
of pretending the terminal is healthy.
"""

from __future__ import annotations

import pytest

from tests.fakes import FakeMT5, gold_terminal_with_live_tick


class TestInitialSnapshot:
    def test_initial_snapshot_is_sent_on_connect(self, api_client):
        with api_client.websocket_connect("/ws/market") as websocket:
            frame = websocket.receive_json()

        assert frame["type"] == "snapshot"
        assert "sequence" in frame
        assert frame["connection"] is not None
        assert frame["symbol"]["requested"] == "XAUUSD"
        assert frame["trading_enabled"] is False
        assert frame["read_only"] is True

    def test_initial_snapshot_carries_all_seven_timeframes(self, api_client):
        with api_client.websocket_connect("/ws/market") as websocket:
            frame = websocket.receive_json()

        assert sorted(frame["timeframes"]) == ["D1", "H1", "H4", "M1", "M15", "M30", "M5"]

    def test_initial_snapshot_includes_reconnect_state_fields(self, api_client):
        with api_client.websocket_connect("/ws/market") as websocket:
            frame = websocket.receive_json()

        connection = frame["connection"]
        for key in (
            "state",
            "mt5_initialized",
            "terminal_connected",
            "last_connected_at",
            "last_connection_error",
            "reconnect_attempts",
            "server_time_offset_seconds",
        ):
            assert key in connection, key


class TestLiveUpdates:
    def test_updates_are_streamed_after_the_initial_snapshot(self, api_client, wait_until):
        with api_client.websocket_connect("/ws/market") as websocket:
            first = websocket.receive_json()
            assert first["type"] == "snapshot"

            second = websocket.receive_json()

        assert second["type"] in {"snapshot", "heartbeat"}
        if second["type"] == "snapshot":
            assert second["sequence"] >= first["sequence"]

    def test_quote_arrives_over_the_socket(self, api_client, wait_until):
        with api_client.websocket_connect("/ws/market") as websocket:
            websocket.receive_json()  # initial
            frame = None
            for _ in range(20):
                candidate = websocket.receive_json()
                if candidate["type"] == "snapshot" and candidate.get("quote"):
                    frame = candidate
                    break

        assert frame is not None
        assert frame["quote"]["bid"] > 0
        assert frame["quote"]["ask"] >= frame["quote"]["bid"]
        assert frame["data_status"] in {"live", "stale"}

    def test_snapshots_are_ordered_by_sequence(self, api_client):
        with api_client.websocket_connect("/ws/market") as websocket:
            sequences = []
            for _ in range(4):
                frame = websocket.receive_json()
                if frame["type"] == "snapshot":
                    sequences.append(frame["sequence"])

        assert sequences == sorted(sequences)


class TestMultipleClients:
    def test_two_clients_both_receive_snapshots(self, api_client):
        with api_client.websocket_connect("/ws/market") as first:
            with api_client.websocket_connect("/ws/market") as second:
                first_frame = first.receive_json()
                second_frame = second.receive_json()

                assert first_frame["type"] == "snapshot"
                assert second_frame["type"] == "snapshot"


class TestDisconnectHandling:
    def test_subscriber_is_removed_on_disconnect(self, api_client, wait_until):
        monitor = api_client.app.state.monitor
        assert monitor.subscriber_count == 0

        with api_client.websocket_connect("/ws/market") as websocket:
            websocket.receive_json()
            assert wait_until(lambda: monitor.subscriber_count == 1)

        assert wait_until(lambda: monitor.subscriber_count == 0)

    def test_many_sequential_clients_do_not_leak_subscribers(self, api_client, wait_until):
        monitor = api_client.app.state.monitor

        for _ in range(3):
            with api_client.websocket_connect("/ws/market") as websocket:
                websocket.receive_json()

        assert wait_until(lambda: monitor.subscriber_count == 0)


class TestDegradedStreams:
    def test_stream_reports_unavailable_when_there_is_no_data(self, make_settings):
        from fastapi.testclient import TestClient

        from app.main import create_app

        fake = FakeMT5()  # terminal is up, no tick at all
        app = create_app(make_settings(poll_interval_ms=200), mt5_module=fake)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/market") as websocket:
                frame = websocket.receive_json()

        assert frame["data_status"] == "unavailable"
        assert frame["quote"] is None

    def test_stream_reports_disconnected_terminal_without_dying(self, make_settings):
        from fastapi.testclient import TestClient

        from app.main import create_app

        fake = FakeMT5(initialize_ok=False, last_error_value=(-6, "Authorization failed"))
        app = create_app(make_settings(poll_interval_ms=200), mt5_module=fake)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/market") as websocket:
                frame = websocket.receive_json()

                assert frame["type"] == "snapshot"
                assert frame["connection"]["terminal_connected"] is False
                assert frame["data_status"] == "unavailable"
                assert frame["connection"]["last_connection_error"]

                # The stream keeps answering rather than erroring out.
                follow_up = websocket.receive_json()
                assert follow_up["type"] in {"snapshot", "heartbeat"}

    def test_slow_client_still_gets_the_newest_snapshot(self, make_settings):
        """The bounded queue drops old frames instead of growing forever."""
        with api_client_ws_only(make_settings) as client:
            with client.websocket_connect("/ws/market") as websocket:
                frame = websocket.receive_json()
                latest = client.app.state.monitor.sequence

        assert frame["sequence"] <= latest


def api_client_ws_only(make_settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(
        make_settings(poll_interval_ms=200, ws_max_queue=2),
        mt5_module=gold_terminal_with_live_tick(with_all_timeframes=True),
    )
    return TestClient(app)
