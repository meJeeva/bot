"""Layered demo-account authorization.

Every case here must prove the same property: when any layer fails, the
authority that the order-submission adapter consults refuses to arm - and the
adapter's own gate raises. The adapter itself is never called (that is proven
again at the adapter layer in ``test_adapter.py``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.execution.authorization import (
    AccountIdentity,
    DemoAccountVerifier,
    ExecutionAuthState,
    ExecutionAuthorization,
)
from app.execution.errors import AuthorizationError, ExecutionStateError
from app.schemas.status import AccountType

DEMO_LOGIN = 5057247615
DEMO_SERVER = "MetaQuotes-Demo"


def make_settings(**overrides) -> Settings:
    base = dict(
        execution_enabled=True,
        execution_demo_login=DEMO_LOGIN,
        execution_demo_server=DEMO_SERVER,
    )
    base.update(overrides)
    return Settings(**base)


def make_account(
    *,
    login: int = DEMO_LOGIN,
    server: str = DEMO_SERVER,
    account_type: AccountType = AccountType.DEMO,
    trade_mode: int | None = 0,
) -> AccountIdentity:
    return AccountIdentity(
        login=login,
        server=server,
        trade_mode=trade_mode,
        account_type=account_type,
        currency="USD",
        equity=10_000.0,
        balance=10_000.0,
        margin_free=10_000.0,
        leverage=100,
    )


def make_authorization(settings: Settings | None = None):
    settings = settings or make_settings()
    return ExecutionAuthorization(DemoAccountVerifier(settings))


class TestDisabledByDefault:
    def test_authorization_starts_disabled_and_never_armed(self):
        auth = make_authorization()
        assert auth.state is ExecutionAuthState.DISABLED
        assert auth.armed is False

    def test_adapter_gate_raises_while_disabled(self):
        auth = make_authorization()
        with pytest.raises(AuthorizationError) as info:
            auth.assert_ready_for_submission()
        assert info.value.code == "execution_not_armed"

    def test_unconfigured_execution_stays_disabled_even_with_a_perfect_account(self):
        auth = make_authorization(Settings())
        outcome = auth.refresh(
            make_account(), terminal_connected=True, mt5_initialized=True
        )
        assert outcome.ok is False
        assert "execution_not_configured" in outcome.reasons
        assert auth.state is ExecutionAuthState.DISABLED
        with pytest.raises(AuthorizationError):
            auth.assert_ready_for_submission()

    def test_successful_verification_never_arms_by_itself(self):
        auth = make_authorization()
        auth.refresh(make_account(), terminal_connected=True, mt5_initialized=True)
        assert auth.state is ExecutionAuthState.DEMO_VERIFIED
        assert auth.armed is False
        with pytest.raises(AuthorizationError):
            auth.assert_ready_for_submission()


class TestVerificationLayers:
    @pytest.mark.parametrize(
        "account,terminal,initialized,expected_reason",
        [
            (None, True, True, "account_info_unavailable"),
            (make_account(login=111111), True, True, "account_login_mismatch"),
            (make_account(server="Some-Other-Broker"), True, True, "account_server_mismatch"),
            (
                make_account(account_type=AccountType.LIVE, trade_mode=2),
                True,
                True,
                "account_not_conclusively_demo",
            ),
            (
                make_account(account_type=AccountType.UNKNOWN, trade_mode=None),
                True,
                True,
                "account_not_conclusively_demo",
            ),
            (
                make_account(account_type=AccountType.UNKNOWN, trade_mode=1),
                True,
                True,
                "account_not_conclusively_demo",
            ),
            (make_account(), False, True, "terminal_disconnected"),
            (make_account(), True, False, "mt5_not_initialized"),
        ],
    )
    def test_each_failed_layer_blocks_verification_and_the_adapter_gate(
        self, account, terminal, initialized, expected_reason
    ):
        auth = make_authorization()
        outcome = auth.refresh(
            account, terminal_connected=terminal, mt5_initialized=initialized
        )

        assert outcome.ok is False
        assert any(expected_reason in reason for reason in outcome.reasons)
        assert auth.armed is False
        with pytest.raises(AuthorizationError):
            auth.assert_ready_for_submission()

    def test_live_account_is_rejected_by_classification_not_by_name(self):
        """A demo-sounding name must not matter; trade_mode decides."""
        verifier = DemoAccountVerifier(make_settings())
        live_with_demo_name = AccountIdentity(
            login=DEMO_LOGIN,
            server="MetaQuotes-Demo-Account-Live",  # "demo" in the name
            trade_mode=2,
            account_type=AccountType.LIVE,
            currency="USD",
            equity=10_000.0,
            balance=10_000.0,
            margin_free=10_000.0,
        )
        outcome = verifier.verify(
            live_with_demo_name, terminal_connected=True, mt5_initialized=True
        )
        assert outcome.ok is False
        assert any("account_not_conclusively_demo" in r for r in outcome.reasons)

    def test_identity_mismatch_reasons_never_leak_the_full_login(self):
        auth = make_authorization()
        outcome = auth.refresh(
            make_account(login=222222222),
            terminal_connected=True,
            mt5_initialized=True,
        )
        blob = " ".join(outcome.reasons)
        assert "222222222" not in blob
        assert "****7615" in blob  # masked tail of the configured login only

    def test_happy_path_reaches_demo_verified(self):
        auth = make_authorization()
        outcome = auth.refresh(
            make_account(), terminal_connected=True, mt5_initialized=True
        )
        assert outcome.ok is True
        assert auth.state is ExecutionAuthState.DEMO_VERIFIED
        assert auth.identity is not None
        assert auth.identity.account_type is AccountType.DEMO


class TestArmingAndRevocation:
    def test_enable_arms_only_from_demo_verified(self):
        auth = make_authorization()
        auth.refresh(make_account(), terminal_connected=True, mt5_initialized=True)

        identity = auth.enable()

        assert auth.state is ExecutionAuthState.ARMED
        assert auth.armed is True
        assert auth.armed_at is not None
        assert identity.login == DEMO_LOGIN
        assert auth.assert_ready_for_submission().login == DEMO_LOGIN

    def test_enable_without_verification_is_rejected(self):
        auth = make_authorization()
        with pytest.raises(ExecutionStateError):
            auth.enable()
        assert auth.armed is False

    def test_enable_without_configuration_names_the_missing_config(self):
        auth = make_authorization(Settings())
        with pytest.raises(AuthorizationError) as info:
            auth.enable()
        assert info.value.code == "execution_not_configured"

    def test_enable_while_blocked_by_a_failed_layer_is_rejected(self):
        auth = make_authorization()
        auth.refresh(
            make_account(login=99999), terminal_connected=True, mt5_initialized=True
        )
        assert auth.state is ExecutionAuthState.BLOCKED
        with pytest.raises(ExecutionStateError):
            auth.enable()
        with pytest.raises(AuthorizationError):
            auth.assert_ready_for_submission()

    def test_disconnect_revokes_a_previously_armed_authority(self):
        auth = make_authorization()
        auth.refresh(make_account(), terminal_connected=True, mt5_initialized=True)
        auth.enable()

        outcome = auth.refresh(
            make_account(), terminal_connected=False, mt5_initialized=True
        )

        assert outcome.ok is False
        assert auth.state is ExecutionAuthState.BLOCKED
        assert auth.armed is False
        with pytest.raises(AuthorizationError):
            auth.assert_ready_for_submission()

    def test_account_change_while_armed_revokes_and_blocks(self):
        auth = make_authorization()
        auth.refresh(make_account(), terminal_connected=True, mt5_initialized=True)
        auth.enable()

        # The terminal switches to a different demo account at runtime.
        outcome = auth.refresh(
            make_account(login=444444444),
            terminal_connected=True,
            mt5_initialized=True,
        )

        assert outcome.ok is False or auth.state is ExecutionAuthState.BLOCKED
        assert auth.armed is False
        assert auth.verified_identity is None
        with pytest.raises(AuthorizationError):
            auth.assert_ready_for_submission()

    def test_re_verification_success_does_not_rearm_automatically(self):
        auth = make_authorization()
        auth.refresh(make_account(), terminal_connected=True, mt5_initialized=True)
        auth.enable()
        auth.refresh(
            make_account(), terminal_connected=False, mt5_initialized=True
        )  # revoked
        assert auth.armed is False

        auth.refresh(make_account(), terminal_connected=True, mt5_initialized=True)

        # Account layers pass again, but the authority must stay disarmed
        # until a fresh operator enable.
        assert auth.state is ExecutionAuthState.DEMO_VERIFIED
        assert auth.armed is False
        with pytest.raises(AuthorizationError):
            auth.assert_ready_for_submission()

    def test_disable_disarms_immediately(self):
        auth = make_authorization()
        auth.refresh(make_account(), terminal_connected=True, mt5_initialized=True)
        auth.enable()

        auth.disable()

        assert auth.armed is False
        with pytest.raises(AuthorizationError):
            auth.assert_ready_for_submission()

    def test_disable_does_not_clear_a_safety_block(self):
        auth = make_authorization()
        auth.refresh(
            make_account(login=99999), terminal_connected=True, mt5_initialized=True
        )
        assert auth.state is ExecutionAuthState.BLOCKED

        auth.disable()

        assert auth.state is ExecutionAuthState.BLOCKED
        with pytest.raises(ExecutionStateError):
            auth.enable()

    def test_block_records_persistent_reasons(self):
        auth = make_authorization()
        auth.refresh(make_account(), terminal_connected=True, mt5_initialized=True)
        auth.enable()

        auth.block("daily_loss_lockout")

        assert auth.state is ExecutionAuthState.BLOCKED
        assert auth.reasons == ("daily_loss_lockout",)
        assert auth.armed is False

    def test_shutdown_style_sequence_releases_the_authority(self):
        """Disarm on shutdown leaves nothing armed for a later stale caller."""
        auth = make_authorization()
        auth.refresh(make_account(), terminal_connected=True, mt5_initialized=True)
        auth.enable()
        auth.disable()
        auth.refresh(
            make_account(), terminal_connected=False, mt5_initialized=False
        )
        assert auth.armed is False
        with pytest.raises(AuthorizationError):
            auth.assert_ready_for_submission()
