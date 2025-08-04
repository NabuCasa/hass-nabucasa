"""Test the payments connection details API."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

from aiohttp import ClientError
import pytest

from hass_nabucasa.payments_api import (
    MigratePaypalAgreementInfo,
    PaymentsApi,
    PaymentsApiError,
    SubscriptionInfo,
)

if TYPE_CHECKING:
    from hass_nabucasa import Cloud
    from tests.utils.aiohttp import AiohttpClientMocker

API_HOSTNAME = "example.com"


@pytest.fixture(autouse=True)
def set_hostname(auth_cloud_mock):
    """Set API hostname for the mock cloud service."""
    auth_cloud_mock.accounts_server = API_HOSTNAME


@pytest.mark.parametrize(
    "exception,getmockargs,log_msg,exception_msg",
    [
        [
            PaymentsApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for get from example.com/payments/subscription_info (500)",
            "Failed to parse API response",
        ],
        [
            PaymentsApiError,
            {"status": 429, "text": "Too fast"},
            "Response for get from example.com/payments/subscription_info (429)",
            "Failed to parse API response",
        ],
        [
            PaymentsApiError,
            {"exc": TimeoutError()},
            "",
            "Timeout reached while calling API",
        ],
        [
            PaymentsApiError,
            {"exc": ClientError("boom!")},
            "",
            "Failed to fetch: boom!",
        ],
        [
            PaymentsApiError,
            {"exc": Exception("boom!")},
            "",
            "Unexpected error while calling API: boom!",
        ],
    ],
)
async def test_problems_getting_connection_details(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    getmockargs,
    log_msg,
    exception_msg,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems getting connection details."""
    payments_api = PaymentsApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/payments/subscription_info",
        **getmockargs,
    )

    with pytest.raises(exception, match=exception_msg):
        await payments_api.subscription_info()

    if log_msg:
        assert log_msg in caplog.text


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
    auth_cloud_mock: Cloud,
    response: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test getting connection details."""
    payments_api = PaymentsApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/payments/subscription_info",
        json=response,
    )

    details = await payments_api.subscription_info()

    assert details == SubscriptionInfo(**response)
    assert (
        "Response for get from example.com/payments/subscription_info (200)"
        in caplog.text
    )


async def test_trigger_async_renew_access_token(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test getting connection details."""
    auth_cloud_mock.started = False
    auth_cloud_mock.auth.async_renew_access_token.side_effect = AsyncMock()

    payments_api = PaymentsApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/payments/subscription_info",
        json={"provider": "legacy"},
    )

    await payments_api.subscription_info()
    assert auth_cloud_mock.auth.async_renew_access_token.call_count == 1

    assert (
        "Response for get from example.com/payments/subscription_info (200)"
        in caplog.text
    )


@pytest.mark.parametrize(
    "exception,postmockargs,log_msg,exception_msg",
    [
        [
            PaymentsApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for post from "
            "example.com/payments/migrate_paypal_agreement (500)",
            "Failed to fetch: (500) ",
        ],
        [
            PaymentsApiError,
            {"status": 429, "text": "Too fast"},
            "Response for post from "
            "example.com/payments/migrate_paypal_agreement (429)",
            "Failed to fetch: (429) ",
        ],
        [
            PaymentsApiError,
            {"exc": TimeoutError()},
            "",
            "Timeout reached while calling API",
        ],
        [
            PaymentsApiError,
            {"exc": ClientError("boom!")},
            "",
            "Failed to fetch: boom!",
        ],
        [
            PaymentsApiError,
            {"exc": Exception("boom!")},
            "",
            "Unexpected error while calling API: boom!",
        ],
    ],
)
async def test_problems_migrating_paypal_agreement(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    postmockargs,
    log_msg,
    exception_msg,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems migrating PayPal agreement."""
    payments_api = PaymentsApi(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/payments/migrate_paypal_agreement",
        **postmockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await payments_api.migrate_paypal_agreement()

    if log_msg:
        assert log_msg in caplog.text


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
    auth_cloud_mock: Cloud,
    response: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test successful PayPal agreement migration."""
    payments_api = PaymentsApi(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/payments/migrate_paypal_agreement",
        json=response,
    )

    result = await payments_api.migrate_paypal_agreement()

    assert result == MigratePaypalAgreementInfo(**response)
    assert (
        "Response for post from example.com/payments/migrate_paypal_agreement (200)"
        in caplog.text
    )


async def test_no_token_refresh_when_cloud_started(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
):
    """Test that token refresh is not triggered when cloud is already started."""
    auth_cloud_mock.started = True
    auth_cloud_mock.auth.async_renew_access_token.side_effect = AsyncMock()

    payments_api = PaymentsApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/payments/subscription_info",
        json={"provider": "legacy"},
    )

    await payments_api.subscription_info()
    assert auth_cloud_mock.auth.async_renew_access_token.call_count == 0


async def test_no_token_refresh_when_no_provider(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
):
    """Test that token refresh is not triggered when no provider is present."""
    auth_cloud_mock.started = False
    auth_cloud_mock.auth.async_renew_access_token.side_effect = AsyncMock()

    payments_api = PaymentsApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/payments/subscription_info",
        json={"provider": None},
    )

    await payments_api.subscription_info()
    assert auth_cloud_mock.auth.async_renew_access_token.call_count == 0


async def test_no_token_refresh_when_skip_renew(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
):
    """Test that token refresh is not triggered when skip_renew is True."""
    auth_cloud_mock.started = False
    auth_cloud_mock.auth.async_renew_access_token.side_effect = AsyncMock()

    payments_api = PaymentsApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/payments/subscription_info",
        json={"provider": "legacy"},
    )

    await payments_api.subscription_info(skip_renew=True)
    assert auth_cloud_mock.auth.async_renew_access_token.call_count == 0


async def test_token_refresh_debug_log(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test that debug log is written when token refresh is triggered."""
    auth_cloud_mock.started = False
    auth_cloud_mock.auth.async_renew_access_token.side_effect = AsyncMock()

    payments_api = PaymentsApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/payments/subscription_info",
        json={"provider": "legacy"},
    )

    with caplog.at_level(logging.DEBUG):
        await payments_api.subscription_info()

    assert (
        "Found disconnected account with valid subscription, connecting" in caplog.text
    )
    assert auth_cloud_mock.auth.async_renew_access_token.call_count == 1
