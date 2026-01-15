"""Tests for Account API."""

import re
from typing import Any

from aiohttp import ClientError
import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa import Cloud
from hass_nabucasa.account_api import (
    AccountApiError,
    AccountServicesDetails,
)
from tests.common import extract_log_messages
from tests.utils.aiohttp import AiohttpClientMocker


@pytest.mark.parametrize(
    "exception,mockargs,exception_msg",
    [
        [
            AccountApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Failed to parse API response",
        ],
        [
            AccountApiError,
            {"status": 429, "text": "Too fast"},
            "Failed to parse API response",
        ],
        [
            AccountApiError,
            {"exc": TimeoutError()},
            "Timeout reached while calling API",
        ],
        [
            AccountApiError,
            {"exc": ClientError("boom!")},
            "Failed to fetch: boom!",
        ],
        [
            AccountApiError,
            {"exc": Exception("boom!")},
            "Unexpected error while calling API: boom!",
        ],
    ],
    ids=["500-error", "429-error", "timeout", "client-error", "unexpected-error"],
)
async def test_problems_getting_services(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    mockargs: dict[str, Any],
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test problems getting account services."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/account/services",
        **mockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await cloud.account.services()

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.parametrize(
    "services_response",
    [{"alexa": {"available": True}, "storage": {"available": False}}],
)
async def test_getting_services(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    services_response: AccountServicesDetails,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test getting account services."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/account/services",
        json=services_response,
    )

    services = await cloud.account.services()

    assert services == services_response
    assert extract_log_messages(caplog) == snapshot
