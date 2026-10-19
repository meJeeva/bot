"""MetaTrader 5 order submission adapter (Phase 4).

This is the only place in the entire codebase that may reach MetaTrader
order submission functions. Every safety check runs before this point:

* static demo identity validation (authorization),
* dynamic operational checks (authorization.refresh),
* signal eligibility (live-only setup with live/verified state),
* risk assessment (sizing limits, stop/take validation),
* daily-loss, drawdown and aggregate-exposure caps,
* persistent idempotency and reconciliation.

The adapter itself re-checks the authorization on every submission; no
upstream call, frontend request or cached state can bypass this guard.
"""

from __future__ import annotations

from typing import Any

from ..execution import (
    AccountIdentity,
    ExecutionAuthorization,
    ExecutionError,
    RiskRejectedError,
    AuthorizationError,
)
from ..schemas.execution import RiskAssessment
from ..execution.risk import SymbolSpec
from ..mt5.connection import MT5Connection


class Mt5ExecutionAdapter:
    """Secure gateway to MetaTrader 5 execution functions.

    Only authorized after *every* fail-closed layer has passed and must
    re-validate before *every* order-submission call. No automatic orders
    ever leave this package.
    """

    def __init__(
        self,
        connection: MT5Connection,
        authorization: ExecutionAuthorization,
    ) -> None:
        self._connection = connection
        self._authorization = authorization

    def submit_strategy_setup(
        self,
        risk: RiskAssessment,
        symbol_spec: SymbolSpec,
        setup_meta: dict[str, Any],
    ) -> dict[str, Any]:
        """One authorized entry point - submits to MetaTrader.

        Every parameter here is system-validated before reaching the
        underlying MT5 order submission. The adapter is the only layer
        that may call ``mt5.order_send`` and re-checks authorization.

        Returns:
            The execution record details from MetaTrader.
        """
        # Final authorization check - the gate.
        identity = self._authorization.assert_ready_for_submission()

        # Calculate the order size according to risk assessment.
        # The broker calculates margin exactly; we only provide volume.
        volume = risk.proposed_volume
        if volume is None or volume <= 0:
            raise RiskRejectedError(
                "risk_volume_not_valid",
                f"Invalid volume {volume} for setup {risk.setup_id}",
                detail={"volume": volume, "setup_id": risk.setup_id},
            )

        # Prepare the order parameters using broker-authoritative calculations.
        # The identity and risk assessment have already been validated.
        mt5 = self._connection.mt5
        order_params: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol_spec.name,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if symbol_spec.direction == "buy" else mt5.ORDER_TYPE_SELL,
            "price": symbol_spec.entry_price,
            "stoploss": symbol_spec.stop_loss,
            "takeprofit": symbol_spec.take_profit,
            "comment": f"setup:{risk.setup_id}",
            "magic": 1133,  # project identifier for demo-only execution
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        # Pass through to MetaTrader after every safety gate.
        mt_result = self._connection.call(mt5.order_send, order_params)

        return {
            "setup_id": risk.setup_id,
            "order_result": mt_result._asdict() if hasattr(mt_result, "_asdict") else mt_result,
            "volume": volume,
            "identity": {
                "login": identity.login,
                "server": identity.server,
                "account_type": identity.account_type.value,
            },
            "timestamp": self._connection.mt5.symbol_info_tick(symbol_spec.name).time,
        }

    def verify_authorization(self) -> dict[str, Any]:
        """Query current authorization posture.

        Returns the state needed by the API to reflect live readiness.
        """
        return {
            "state": self._authorization.state.value,
            "armed": self._authorization.armed,
            "configured": self._authorization.configured,
            "identity": {
                "login": self._authorization.identity.login if self._authorization.identity else None,
                "server": self._authorization.identity.server if self._authorization.identity else None,
            } if self._authorization.identity else None,
        }