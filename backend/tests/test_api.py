"""REST endpoint contracts.

Every test here runs the real FastAPI application with a fake MetaTrader
module, so routing, validation, serialization and error envelopes are all
exercised for real.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.mt5.timeframes import SUPPORTED_TIMEFRAMES
from tests.fakes import FakeMT5, FakeSymbolInfo, FakeTick, broker_time, gold_terminal_with_live_tick


def client_for(make_settings, fake: FakeMT5, **overrides) -> TestClient:
    from app.main import create_app

    overrides.setdefault("poll_interval_ms", 200)
    app = create_app(make_settings(**overrides), mt5_module=fake)
    return TestClient(app)


def live_client(make_settings, **overrides) -> TestClient:
    return client_for(
        make_settings, gold_terminal_with_live_tick(with_all_timeframes=True), **overrides
    )


# ======================================================================
# /api/mt5/status
# ======================================================================
class TestMT5Status:
    def test_reports_a_connected_demo_terminal(self, make_settings):
        with live_client(make_settings) as client:
            response = client.get("/api/mt5/status")

        assert response.status_code == 200
        body = response.json()
        status = body["status"]

        assert status["mt5_initialized"] is True
        assert status["terminal_connected"] is True
        assert status["trading_server"] == "MetaQuotes-Demo"
        assert status["account_type"] == "demo"
        assert status["account_currency"] == "USD"
        assert status["trading_enabled"] is False
        assert status["read_only"] is True
        assert status["last_connected_at"] is not None

    def test_account_login_is_masked(self, make_settings):
        with live_client(make_settings) as client:
            status = client.get("/api/mt5/status").json()["status"]

        assert status["account_login_masked"] == "******7615"
        assert status["account_login"] is None

    def test_reports_the_resolved_symbol(self, make_settings):
        with live_client(make_settings) as client:
            body = client.get("/api/mt5/status").json()

        symbol = body["symbol"]
        assert symbol["resolution"] == "resolved"
        assert symbol["resolved"] == "XAUUSD"
        assert symbol["info"]["digits"] == 2
        assert symbol["info"]["point"] == 0.01

    def test_disconnected_terminal_is_a_state_not_an_error(self, make_settings):
        fake = FakeMT5(initialize_ok=False, last_error_value=(-6, "Authorization failed"))
        with client_for(make_settings, fake) as client:
            response = client.get("/api/mt5/status")

        assert response.status_code == 200
        assert response.json()["status"]["terminal_connected"] is False

    def test_credentials_never_appear_in_the_response(self, make_settings):
        fake = gold_terminal_with_live_tick()
        with client_for(
            make_settings,
            fake,
            mt5_login=5057247615,
            mt5_password="hunter2",
            mt5_server="MetaQuotes-Demo",
        ) as client:
            text = client.get("/api/mt5/status").text

        assert "hunter2" not in text

    def test_ambiguity_is_surfaced_for_operator_action(self, make_settings):
        fake = FakeMT5(
            symbols=[FakeSymbolInfo("XAUUSDm"), FakeSymbolInfo("XAUUSDc")],
            ticks={"XAUUSDm": FakeTick(time=broker_time())},
        )
        with client_for(make_settings, fake) as client:
            symbol = client.get("/api/mt5/status").json()["symbol"]

        assert symbol["resolution"] == "ambiguous"
        assert symbol["requires_configuration"] is True
        assert sorted(symbol["candidates"]) == ["XAUUSDc", "XAUUSDm"]


# ======================================================================
# /api/market/quote
# ======================================================================
class TestQuoteEndpoint:
    def test_returns_a_live_quote(self, make_settings, wait_until):
        with live_client(make_settings) as client:
            assert wait_until(
                lambda: client.get("/api/market/quote").status_code == 200
            )
            body = client.get("/api/market/quote").json()

        assert body["symbol"] == "XAUUSD"
        assert body["bid"] == pytest.approx(4185.58)
        assert body["ask"] == pytest.approx(4186.14)
        assert body["spread_price"] == pytest.approx(0.56)
        assert body["spread_points"] == pytest.approx(56.0)
        assert body["digits"] == 2
        assert body["point"] == 0.01
        assert body["freshness"] == "live"
        assert body["tick_time_utc"] is not None

    def test_last_price_zero_is_null_not_a_fabricated_number(self, make_settings, wait_until):
        with live_client(make_settings) as client:
            assert wait_until(lambda: client.get("/api/market/quote").status_code == 200)
            body = client.get("/api/market/quote").json()

        assert body["last"] is None

    def test_returns_503_with_an_error_envelope_when_no_tick_exists(self, make_settings):
        fake = FakeMT5()  # symbol exists, no tick published
        with client_for(make_settings, fake) as client:
            response = client.get("/api/market/quote")

        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "quote_unavailable"
        assert error["message"]


# ======================================================================
# /api/market/candles
# ======================================================================
class TestCandlesEndpoint:
    @pytest.mark.parametrize("timeframe", SUPPORTED_TIMEFRAMES)
    def test_every_supported_timeframe_is_accepted(self, make_settings, timeframe, wait_until):
        with live_client(make_settings) as client:
            response = client.get(
                "/api/market/candles", params={"timeframe": timeframe, "limit": 20}
            )

        assert response.status_code == 200
        body = response.json()
        assert body["timeframe"] == timeframe
        assert body["count"] == 20
        assert len(body["candles"]) == 20
        assert body["timeframe_seconds"] > 0

    def test_lowercase_timeframe_is_accepted(self, make_settings):
        with live_client(make_settings) as client:
            response = client.get("/api/market/candles", params={"timeframe": "m15"})

        assert response.status_code == 200
        assert response.json()["timeframe"] == "M15"

    def test_defaults_are_m15_and_the_configured_limit(self, make_settings):
        with live_client(make_settings) as client:
            body = client.get("/api/market/candles").json()

        assert body["timeframe"] == "M15"
        assert body["count"] == 300

    def test_invalid_timeframe_is_rejected_with_the_supported_list(self, make_settings):
        with live_client(make_settings) as client:
            response = client.get("/api/market/candles", params={"timeframe": "X1"})

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "unsupported_timeframe"
        assert error["detail"]["supported"] == list(SUPPORTED_TIMEFRAMES)

    def test_limit_above_the_maximum_is_rejected(self, make_settings):
        with live_client(make_settings, max_candle_limit=500) as client:
            response = client.get(
                "/api/market/candles", params={"timeframe": "M15", "limit": 501}
            )

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "invalid_limit"
        assert error["detail"]["max"] == 500

    def test_zero_and_negative_limits_are_rejected(self, make_settings):
        with live_client(make_settings) as client:
            for value in (0, -5):
                response = client.get(
                    "/api/market/candles", params={"timeframe": "M15", "limit": value}
                )
                assert response.status_code == 400
                assert response.json()["error"]["code"] == "invalid_limit"

    def test_distinguishes_forming_from_closed_candles(self, make_settings):
        with live_client(make_settings) as client:
            body = client.get(
                "/api/market/candles", params={"timeframe": "M15", "limit": 10}
            ).json()

        assert body["latest_candle"] is not None
        assert body["latest_closed_candle"] is not None
        assert body["latest_candle"]["is_closed"] is False
        assert body["latest_closed_candle"]["is_closed"] is True
        assert body["latest_closed_candle"]["time"] < body["latest_candle"]["time"]

    def test_candles_carry_broker_and_utc_timestamps(self, make_settings):
        with live_client(make_settings) as client:
            body = client.get(
                "/api/market/candles", params={"timeframe": "M15", "limit": 3}
            ).json()

        # Second-level precision: allow the sub-second measurement jitter.
        assert abs(body["server_time_offset_seconds"] - 10800) <= 1
        candle = body["candles"][0]
        assert candle["open_time_broker"] > candle["open_time_utc"]

    def test_missing_history_is_a_503_not_a_crash(self, make_settings):
        fake = gold_terminal_with_live_tick()  # tick but no candle history
        with client_for(make_settings, fake) as client:
            response = client.get(
                "/api/market/candles", params={"timeframe": "M15", "limit": 10}
            )

        assert response.status_code == 503
        assert response.json()["error"]["code"] in {"no_candle_data", "empty_candle_data"}


# ======================================================================
# /api/market/snapshot
# ======================================================================
class TestSnapshotEndpoint:
    def test_snapshot_combines_everything_the_dashboard_needs(self, make_settings, wait_until):
        with live_client(make_settings) as client:
            assert wait_until(
                lambda: client.get("/api/market/snapshot").json()["data_status"] == "live"
            )
            body = client.get("/api/market/snapshot").json()

        assert body["type"] == "snapshot"
        assert body["data_status"] == "live"
        assert body["connection"]["terminal_connected"] is True
        assert body["symbol"]["resolved"] == "XAUUSD"
        assert body["quote"]["bid"] > 0
        assert body["last_market_update"] is not None
        assert sorted(body["timeframes"]) == sorted(SUPPORTED_TIMEFRAMES)
        assert body["trading_enabled"] is False
        assert body["read_only"] is True

    def test_snapshot_is_never_green_without_live_data(self, make_settings):
        fake = FakeMT5()
        with client_for(make_settings, fake) as client:
            body = client.get("/api/market/snapshot").json()

        assert body["data_status"] == "unavailable"
        assert body["quote"] is None


# ======================================================================
# Auxiliary endpoints
# ======================================================================
class TestAuxiliaryEndpoints:
    def test_timeframes_endpoint_lists_the_seven(self, api_client):
        body = api_client.get("/api/market/timeframes").json()

        assert [item["name"] for item in body["supported"]] == list(SUPPORTED_TIMEFRAMES)
        assert body["supported"][0]["mt5_value"] == 1

    def test_symbols_endpoint_explains_the_resolution(self, api_client):
        body = api_client.get("/api/market/symbols").json()

        assert body["requested"] == "XAUUSD"
        assert body["resolution"] == "resolved"
        assert body["info"]["digits"] == 2

    def test_root_endpoint_describes_the_phase(self, api_client):
        body = api_client.get("/").json()

        # The phase label tracks the current build; only the label changes.
        assert body["phase"] == "phase-7-strategies-removed-no-trading"
        assert body["read_only"] is True
        assert body["trading_enabled"] is False
        assert "/ws/market" in body["endpoints"]
        assert "/api/execution/status" in body["endpoints"]
        assert "/api/execution/enable" in body["endpoints"]

    def test_openapi_documents_every_documented_endpoint(self, api_client):
        paths = api_client.get("/openapi.json").json()["paths"]

        for path in (
            "/api/health",
            "/api/mt5/status",
            "/api/market/quote",
            "/api/market/candles",
            "/api/market/snapshot",
        ):
            assert path in paths, path

    def test_unknown_route_uses_the_error_envelope(self, api_client):
        response = api_client.get("/api/does-not-exist")

        assert response.status_code == 404
        assert "error" in response.json()


# ======================================================================
# CORS
# ======================================================================
class TestCors:
    def test_allows_the_configured_dashboard_origin(self, api_client):
        response = api_client.get("/api/health", headers={"Origin": "http://localhost:5173"})

        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_does_not_allow_an_unlisted_origin(self, api_client):
        response = api_client.get("/api/health", headers={"Origin": "http://evil.example"})

        assert "access-control-allow-origin" not in response.headers

    def test_preflight_for_an_unlisted_origin_is_refused(self, api_client):
        response = api_client.options(
            "/api/health",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert response.status_code == 400
