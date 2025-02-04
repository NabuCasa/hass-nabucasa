"""Tests for Instance API."""

from typing import Any

from aiohttp import ClientError
import pytest

from hass_nabucasa import Cloud
from hass_nabucasa.account_api import (
    AccountApi,
    AccountApiError,
    AccountServicesDetails,
)
from tests.utils.aiohttp import AiohttpClientMocker

API_HOSTNAME = "example.com"


@pytest.fixture(autouse=True)
def set_hostname(auth_cloud_mock: Cloud):
    """Set API hostname for the mock cloud service."""
    auth_cloud_mock.servicehandlers_server = API_HOSTNAME


@pytest.mark.parametrize(
    "exception,getmockargs,log_msg,exception_msg",
    [
        [
            AccountApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for get from example.com/account/services (500)",
            "Failed to parse API response",
        ],
        [
            AccountApiError,
            {"status": 429, "text": "Too fast"},
            "Response for get from example.com/account/services (429)",
            "Failed to parse API response",
        ],
        [
            AccountApiError,
            {"exc": TimeoutError()},
            "",
            "Timeout reached while calling API",
        ],
        [
            AccountApiError,
            {"exc": ClientError("boom!")},
            "",
            "Failed to fetch: boom!",
        ],
        [
            AccountApiError,
            {"exc": Exception("boom!")},
            "",
            "Unexpected error while calling API: boom!",
        ],
    ],
)
async def test_problems_getting_services(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    getmockargs: dict[str, Any],
    log_msg: str,
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems getting account services."""
    account_api = AccountApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/account/services",
        **getmockargs,
    )

    with pytest.raises(exception, match=exception_msg):
        await account_api.services()

    assert log_msg in caplog.text


@pytest.mark.parametrize(
    "services_response",
    [{"alexa": {"available": True}, "storage": {"available": False}}],
)
async def test_getting_services(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    services_response: AccountServicesDetails,
    caplog: pytest.LogCaptureFixture,
):
    """Test getting account services."""
    account_api = AccountApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/account/services",
        json=services_response,
    )

    services = await account_api.services()

    assert services == services_response
    assert "Response for get from example.com/account/services (200)" in caplog.text
