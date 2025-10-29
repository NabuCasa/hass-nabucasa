"""Test the payments connection details API."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from aiohttp import ClientError
import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa.payments_api import (
    MigratePaypalAgreementInfo,
    PaymentsApiError,
    SubscriptionInfo,
)
from tests.common import extract_log_messages

if TYPE_CHECKING:
    from hass_nabucasa import Cloud
    from tests.utils.aiohttp import AiohttpClientMocker


@pytest.mark.parametrize(
    "exception,getmockargs,exception_msg",
    [
        [
            PaymentsApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Failed to parse API response",
        ],
        [
            PaymentsApiError,
            {"status": 429, "text": "Too fast"},
            "Failed to parse API response",
        ],
        [
            PaymentsApiError,
            {"exc": TimeoutError()},
            "Timeout reached while calling API",
        ],
        [
            PaymentsApiError,
            {"exc": ClientError("boom!")},
            "Failed to fetch: boom!",
        ],
        [
            PaymentsApiError,
            {"exc": Exception("boom!")},
            "Unexpected error while calling API: boom!",
        ],
    ],
)
async def test_problems_getting_connection_details(
    aioclient_mock: AiohttpClientMocker,
    exception: Exception,
    getmockargs,
    exception_msg,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test problems getting connection details."""
    aioclient_mock.get(
        f"https://{cloud.accounts_server}/payments/subscription_info",
        **getmockargs,
    )

    with pytest.raises(exception, match=exception_msg):
        await cloud.payments.subscription_info()

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.parametrize(
    "response",
    [
        {
            "provider": "legacy",
        }
    ],
)
async def test_getting_connection_details(
    aioclient_mock: AiohttpClientMocker,
    response: dict[str, Any],
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test getting connection details."""
    aioclient_mock.get(
        f"https://{cloud.accounts_server}/payments/subscription_info",
        json=response,
    )

    details = await cloud.payments.subscription_info()

    assert details == SubscriptionInfo(**response)
    assert extract_log_messages(caplog) == snapshot


async def test_trigger_async_renew_access_token(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test getting connection details."""
    aioclient_mock.get(
        f"https://{cloud.accounts_server}/payments/subscription_info",
        json={"provider": "legacy"},
    )

    cloud.started = False
    with patch(
        "hass_nabucasa.auth.CognitoAuth.async_renew_access_token",
        new_callable=AsyncMock,
    ) as renew_access_token_mock:
        await cloud.payments.subscription_info()
        assert renew_access_token_mock.call_count == 1

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.parametrize(
    "exception,postmockargs,exception_msg",
    [
        [
            PaymentsApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Failed to fetch: (500)",
        ],
        [
            PaymentsApiError,
            {"status": 429, "text": "Too fast"},
            "Failed to fetch: (429)",
        ],
        [
            PaymentsApiError,
            {"exc": TimeoutError()},
            "Timeout reached while calling API",
        ],
        [
            PaymentsApiError,
            {"exc": ClientError("boom!")},
            "Failed to fetch: boom!",
        ],
        [
            PaymentsApiError,
            {"exc": Exception("boom!")},
            "Unexpected error while calling API: boom!",
        ],
    ],
)
async def test_problems_migrating_paypal_agreement(
    aioclient_mock: AiohttpClientMocker,
    exception: Exception,
    postmockargs,
    exception_msg,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test problems migrating PayPal agreement."""
    aioclient_mock.post(
        f"https://{cloud.accounts_server}/payments/migrate_paypal_agreement",
        **postmockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await cloud.payments.migrate_paypal_agreement()

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.parametrize(
    "response",
    [
        {
            "url": "https://www.paypal.com/agreement/migrate?token=EC-123456789",
        },
        {
            "url": "https://www.sandbox.paypal.com/agreement/migrate?token=EC-987654321",
        },
    ],
)
async def test_migrate_paypal_agreement_success(
    aioclient_mock: AiohttpClientMocker,
    response: dict[str, Any],
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test successful PayPal agreement migration."""
    aioclient_mock.post(
        f"https://{cloud.accounts_server}/payments/migrate_paypal_agreement",
        json=response,
    )

    result = await cloud.payments.migrate_paypal_agreement()

    assert result == MigratePaypalAgreementInfo(**response)
    assert extract_log_messages(caplog) == snapshot


async def test_no_token_refresh_when_cloud_started(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that token refresh is not triggered when cloud is already started."""
    aioclient_mock.get(
        f"https://{cloud.accounts_server}/payments/subscription_info",
        json={"provider": "legacy"},
    )

    cloud.started = True

    with patch(
        "hass_nabucasa.auth.CognitoAuth.async_renew_access_token",
        new_callable=AsyncMock,
    ) as renew_access_token_mock:
        await cloud.payments.subscription_info()
        assert renew_access_token_mock.call_count == 0


async def test_no_token_refresh_when_no_provider(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that token refresh is not triggered when no provider is present."""
    aioclient_mock.get(
        f"https://{cloud.accounts_server}/payments/subscription_info",
        json={"provider": None},
    )
    cloud.started = False
    with patch(
        "hass_nabucasa.auth.CognitoAuth.async_renew_access_token",
        new_callable=AsyncMock,
    ) as renew_access_token_mock:
        await cloud.payments.subscription_info()
        assert renew_access_token_mock.call_count == 0


async def test_no_token_refresh_when_skip_renew(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that token refresh is not triggered when skip_renew is True."""
    aioclient_mock.get(
        f"https://{cloud.accounts_server}/payments/subscription_info",
        json={"provider": "legacy"},
    )

    cloud.started = False
    with patch(
        "hass_nabucasa.auth.CognitoAuth.async_renew_access_token",
        new_callable=AsyncMock,
    ) as renew_access_token_mock:
        await cloud.payments.subscription_info(skip_renew=True)
        assert renew_access_token_mock.call_count == 0


async def test_token_refresh_debug_log(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that debug log is written when token refresh is triggered."""
    aioclient_mock.get(
        f"https://{cloud.accounts_server}/payments/subscription_info",
        json={"provider": "legacy"},
    )

    cloud.started = False
    with patch(
        "hass_nabucasa.auth.CognitoAuth.async_renew_access_token",
        new_callable=AsyncMock,
    ) as renew_access_token_mock:
        with caplog.at_level(logging.DEBUG):
            await cloud.payments.subscription_info()

        assert renew_access_token_mock.call_count == 1
    assert extract_log_messages(caplog) == snapshot
