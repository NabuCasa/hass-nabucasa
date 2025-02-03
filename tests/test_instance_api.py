"""Tests for Instance API."""

from typing import Any

from aiohttp import ClientError
import pytest

from hass_nabucasa import Cloud
from hass_nabucasa.instance_api import (
    InstanceApi,
    InstanceApiError,
    InstanceConnection,
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
            InstanceApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for get from example.com/instance/connection (500)",
            "Failed to parse API response",
        ],
        [
            InstanceApiError,
            {"status": 429, "text": "Too fast"},
            "Response for get from example.com/instance/connection (429)",
            "Failed to parse API response",
        ],
        [
            InstanceApiError,
            {"exc": TimeoutError()},
            "",
            "Timeout reached while calling API",
        ],
        [
            InstanceApiError,
            {"exc": ClientError("boom!")},
            "",
            "Failed to fetch: boom!",
        ],
        [
            InstanceApiError,
            {"exc": Exception("boom!")},
            "",
            "Unexpected error while calling API: boom!",
        ],
    ],
)
async def test_problems_getting_conntection(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    getmockargs: dict[str, Any],
    log_msg: str,
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems getting connection details."""
    instance_api = InstanceApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/instance/connection",
        **getmockargs,
    )

    with pytest.raises(exception, match=exception_msg):
        await instance_api.connection()

    assert log_msg in caplog.text


@pytest.mark.parametrize("connection_response", [{"connected": True, "details": {}}])
async def test_getting_connection(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    connection_response: InstanceConnection,
    caplog: pytest.LogCaptureFixture,
):
    """Test getting connection details."""
    instance_api = InstanceApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/instance/connection",
        json=connection_response,
    )

    connection = await instance_api.connection()

    assert connection == connection_response
    assert "Response for get from example.com/instance/connection (200)" in caplog.text
