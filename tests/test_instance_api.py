"""Tests for Instance API."""

import re
from typing import Any

from aiohttp import ClientError
import pytest

from hass_nabucasa import Cloud
from hass_nabucasa.instance_api import (
    InstanceApi,
    InstanceApiError,
)
from tests.utils.aiohttp import AiohttpClientMocker

API_HOSTNAME = "example.com"


@pytest.fixture(autouse=True)
def set_hostname(auth_cloud_mock: Cloud):
    """Set API hostname for the mock cloud service."""
    auth_cloud_mock.servicehandlers_server = API_HOSTNAME


@pytest.mark.parametrize(
    "exception,mockargs,log_msg_template,exception_msg",
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
    ids=["500-error", "429-error", "timeout", "client-error", "unexpected-error"],
)
async def test_connection_endpoint_problems(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    mockargs: dict[str, Any],
    log_msg_template: str,
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems with connection endpoint."""
    instance_api = InstanceApi(auth_cloud_mock)

    aioclient_mock.get(
        f"https://{API_HOSTNAME}/instance/connection",
        **mockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await instance_api.connection()

    if log_msg_template:
        assert log_msg_template in caplog.text


@pytest.mark.parametrize(
    "exception,mockargs,log_msg_template,exception_msg",
    [
        [
            InstanceApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for post from example.com/instance/dns_challenge_cleanup (500)",
            "Failed to fetch: (500) ",
        ],
        [
            InstanceApiError,
            {"status": 429, "text": "Too fast"},
            "Response for post from example.com/instance/dns_challenge_cleanup (429)",
            "Failed to fetch: (429) ",
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
    ids=["500-error", "429-error", "timeout", "client-error", "unexpected-error"],
)
async def test_cleanup_dns_challenge_record_endpoint_problems(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    mockargs: dict[str, Any],
    log_msg_template: str,
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems with cleanup_dns_challenge_record endpoint."""
    instance_api = InstanceApi(auth_cloud_mock)

    aioclient_mock.post(
        f"https://{API_HOSTNAME}/instance/dns_challenge_cleanup",
        **mockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await instance_api.cleanup_dns_challenge_record(value="challenge-value")

    if log_msg_template:
        assert log_msg_template in caplog.text


@pytest.mark.parametrize(
    "exception,mockargs,log_msg_template,exception_msg",
    [
        [
            InstanceApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for post from example.com/instance/dns_challenge_txt (500)",
            "Failed to fetch: (500) ",
        ],
        [
            InstanceApiError,
            {"status": 429, "text": "Too fast"},
            "Response for post from example.com/instance/dns_challenge_txt (429)",
            "Failed to fetch: (429) ",
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
    ids=["500-error", "429-error", "timeout", "client-error", "unexpected-error"],
)
async def test_create_dns_challenge_record_endpoint_problems(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    mockargs: dict[str, Any],
    log_msg_template: str,
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems with create_dns_challenge_record endpoint."""
    instance_api = InstanceApi(auth_cloud_mock)

    aioclient_mock.post(
        f"https://{API_HOSTNAME}/instance/dns_challenge_txt",
        **mockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await instance_api.create_dns_challenge_record(value="challenge-value")

    if log_msg_template:
        assert log_msg_template in caplog.text


async def test_connection_endpoint_success(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test successful connection endpoint."""
    instance_api = InstanceApi(auth_cloud_mock)
    expected_result = {"connected": True, "details": {}}

    aioclient_mock.get(
        f"https://{API_HOSTNAME}/instance/connection",
        json=expected_result,
    )

    result = await instance_api.connection()

    assert result == expected_result
    assert "Response for get from example.com/instance/connection (200)" in caplog.text


async def test_cleanup_dns_challenge_record_endpoint_success(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test successful cleanup_dns_challenge_record endpoint."""
    instance_api = InstanceApi(auth_cloud_mock)

    aioclient_mock.post(
        f"https://{API_HOSTNAME}/instance/dns_challenge_cleanup",
        json={},
    )

    result = await instance_api.cleanup_dns_challenge_record(value="challenge-value")

    assert result is None
    assert (
        "Response for post from example.com/instance/dns_challenge_cleanup (200)"
        in caplog.text
    )


async def test_create_dns_challenge_record_endpoint_success(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test successful create_dns_challenge_record endpoint."""
    instance_api = InstanceApi(auth_cloud_mock)

    aioclient_mock.post(
        f"https://{API_HOSTNAME}/instance/dns_challenge_txt",
        json={},
    )

    result = await instance_api.create_dns_challenge_record(value="challenge-value")

    assert result is None
    assert (
        "Response for post from example.com/instance/dns_challenge_txt (200)"
        in caplog.text
    )
