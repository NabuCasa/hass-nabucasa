"""Tests for Instance API."""

import re
from typing import Any

from aiohttp import ClientError
import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa import Cloud
from hass_nabucasa.instance_api import (
    InstanceApiError,
)
from tests.common import extract_log_messages
from tests.utils.aiohttp import AiohttpClientMocker

API_HOSTNAME = "example.com"


@pytest.mark.parametrize(
    "exception,mockargs,exception_msg",
    [
        [
            InstanceApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Failed to parse API response",
        ],
        [
            InstanceApiError,
            {"status": 429, "text": "Too fast"},
            "Failed to parse API response",
        ],
        [
            InstanceApiError,
            {"exc": TimeoutError()},
            "Timeout reached while calling API",
        ],
        [
            InstanceApiError,
            {"exc": ClientError("boom!")},
            "Failed to fetch: boom!",
        ],
        [
            InstanceApiError,
            {"exc": Exception("boom!")},
            "Unexpected error while calling API: boom!",
        ],
    ],
    ids=["500-error", "429-error", "timeout", "client-error", "unexpected-error"],
)
async def test_connection_endpoint_problems(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    mockargs: dict[str, Any],
    snapshot: SnapshotAssertion,
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems with connection endpoint."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/instance/connection",
        **mockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await cloud.instance.connection()

    assert snapshot == extract_log_messages(caplog)


@pytest.mark.parametrize(
    "exception,mockargs,exception_msg",
    [
        [
            InstanceApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Failed to fetch: (500) ",
        ],
        [
            InstanceApiError,
            {"status": 429, "text": "Too fast"},
            "Failed to fetch: (429) ",
        ],
        [
            InstanceApiError,
            {"exc": TimeoutError()},
            "Timeout reached while calling API",
        ],
        [
            InstanceApiError,
            {"exc": ClientError("boom!")},
            "Failed to fetch: boom!",
        ],
        [
            InstanceApiError,
            {"exc": Exception("boom!")},
            "Unexpected error while calling API: boom!",
        ],
    ],
    ids=["500-error", "429-error", "timeout", "client-error", "unexpected-error"],
)
async def test_cleanup_dns_challenge_record_endpoint_problems(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    mockargs: dict[str, Any],
    snapshot: SnapshotAssertion,
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems with cleanup_dns_challenge_record endpoint."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/dns_challenge_cleanup",
        **mockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await cloud.instance.cleanup_dns_challenge_record(value="challenge-value")

    assert snapshot == extract_log_messages(caplog)


@pytest.mark.parametrize(
    "exception,mockargs,exception_msg",
    [
        [
            InstanceApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Failed to fetch: (500) ",
        ],
        [
            InstanceApiError,
            {"status": 429, "text": "Too fast"},
            "Failed to fetch: (429) ",
        ],
        [
            InstanceApiError,
            {"exc": TimeoutError()},
            "Timeout reached while calling API",
        ],
        [
            InstanceApiError,
            {"exc": ClientError("boom!")},
            "Failed to fetch: boom!",
        ],
        [
            InstanceApiError,
            {"exc": Exception("boom!")},
            "Unexpected error while calling API: boom!",
        ],
    ],
    ids=["500-error", "429-error", "timeout", "client-error", "unexpected-error"],
)
async def test_create_dns_challenge_record_endpoint_problems(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    mockargs: dict[str, Any],
    snapshot: SnapshotAssertion,
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems with create_dns_challenge_record endpoint."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/dns_challenge_txt",
        **mockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await cloud.instance.create_dns_challenge_record(value="challenge-value")

    assert snapshot == extract_log_messages(caplog)


async def test_connection_endpoint_success(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test successful connection endpoint."""
    expected_result = {"connected": True, "details": {}}

    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/instance/connection",
        json=expected_result,
    )

    result = await cloud.instance.connection()

    assert result == expected_result
    assert snapshot == extract_log_messages(caplog)


async def test_cleanup_dns_challenge_record_endpoint_success(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test successful cleanup_dns_challenge_record endpoint."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/dns_challenge_cleanup",
        json={},
    )

    result = await cloud.instance.cleanup_dns_challenge_record(value="challenge-value")

    assert result is None
    assert snapshot == extract_log_messages(caplog)


async def test_create_dns_challenge_record_endpoint_success(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test successful create_dns_challenge_record endpoint."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/instance/dns_challenge_txt",
        json={},
    )

    result = await cloud.instance.create_dns_challenge_record(value="challenge-value")

    assert result is None
    assert snapshot == extract_log_messages(caplog)
