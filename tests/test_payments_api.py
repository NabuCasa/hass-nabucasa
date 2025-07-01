"""Test the payments connection details API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

from aiohttp import ClientError
import pytest

from hass_nabucasa.payments_api import (
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
