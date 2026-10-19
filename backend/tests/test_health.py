"""``GET /api/health``.

Health must stay answerable even when MetaTrader is unreachable, and it must
report ``degraded`` rather than pretending everything is fine.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeMT5


class TestHealthyBackend:
    def test_health_returns_200_with_the_documented_shape(self, api_client, wait_until):
        response = api_client.get("/api/health")

        assert response.status_code == 200
        body = response.json()
        for key in (
            "status",
            "app_name",
            "version",
            "environment",
            "started_at",
            "uptime_seconds",
            "read_only",
            "trading_enabled",
            "mt5_initialized",
            "terminal_connected",
            "data_status",
            "timestamp",
        ):
            assert key in body, key

    def test_reports_live_once_market_data_is_flowing(self, api_client, wait_until):
        assert wait_until(lambda: api_client.get("/api/health").json()["data_status"] == "live")

        body = api_client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["terminal_connected"] is True
        assert body["mt5_initialized"] is True

    def test_always_declares_phase1_is_read_only(self, api_client):
        body = api_client.get("/api/health").json()

        assert body["read_only"] is True
        assert body["trading_enabled"] is False

    def test_uptime_is_non_negative_and_advances(self, api_client):
        first = api_client.get("/api/health").json()["uptime_seconds"]
        time.sleep(0.2)
        second = api_client.get("/api/health").json()["uptime_seconds"]

        assert first >= 0
        assert second >= first

    def test_version_and_environment_are_reported(self, api_client):
        body = api_client.get("/api/health").json()

        assert body["version"] == "0.1.0"
        assert body["environment"] == "development"
        assert body["app_name"]


class TestDegradedBackend:
    def test_no_market_data_yet_is_reported_as_degraded(self, make_settings):
        fake = FakeMT5()  # terminal runs, but no tick is published
        app = _client_app(make_settings, fake)
        with TestClient(app) as client:
            body = client.get("/api/health").json()

        assert body["status"] == "degraded"
        assert body["data_status"] == "unavailable"
        assert body["terminal_connected"] is True

    def test_terminal_that_cannot_connect_still_answers_health(self, make_settings):
        fake = FakeMT5(initialize_ok=False, last_error_value=(-6, "Authorization failed"))
        app = _client_app(make_settings, fake)
        with TestClient(app) as client:
            response = client.get("/api/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["mt5_initialized"] is False
        assert body["terminal_connected"] is False

    def test_health_does_not_leak_credentials(self, make_settings):
        fake = FakeMT5()
        # A password is only valid with a login AND a server, so the fixture
        # supplies the full credential triple; the assertion is that none of it
        # reaches the response.
        app = _client_app(
            make_settings,
            fake,
            mt5_password="hunter2",
            mt5_login=5057247615,
            mt5_server="MetaQuotes-Demo",
        )
        with TestClient(app) as client:
            text = client.get("/api/health").text

        assert "hunter2" not in text


def _client_app(make_settings, fake, **overrides):
    from app.main import create_app

    overrides.setdefault("poll_interval_ms", 200)
    return create_app(make_settings(**overrides), mt5_module=fake)
