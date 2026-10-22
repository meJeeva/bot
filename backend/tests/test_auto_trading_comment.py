import time
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.services.auto_trading import AutoTradingController
from tests.fakes import gold_terminal_with_live_tick

@pytest.fixture
def patched_controller(monkeypatch):
    def _nb(self):
        return datetime.now(timezone.utc)
    async def _sleep(self, target, event):
        return None
    monkeypatch.setattr(AutoTradingController, "_next_minute_boundary", _nb)
    monkeypatch.setattr(AutoTradingController, "_sleep_until", _sleep)
    return True

def test_entry_comment_short(patched_controller):
    fake = gold_terminal_with_live_tick(with_all_timeframes=True)
    settings = Settings(_env_file=None, database_enabled=False, log_level="WARNING", poll_interval_ms=200, auto_trade_max_cycles=1)
    app = create_app(settings, mt5_module=fake)
    with TestClient(app) as client:
        time.sleep(1)
        r = client.post("/api/auto-trading/start")
        assert r.status_code == 200
        time.sleep(2)
        client.post("/api/auto-trading/stop")
    order_calls = [c for c in fake.calls if c[0] == "order_send"]
    assert order_calls, "expected an order_send call"
    req = order_calls[0][1][0]
    comment = req["comment"] if isinstance(req, dict) else req.comment
    assert len(comment) <= 31
    assert comment.startswith("AU_M1_B")
