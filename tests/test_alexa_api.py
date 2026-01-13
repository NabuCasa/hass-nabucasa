"""Test the Alexa access token API."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError
import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa.alexa_api import (
    AlexaAccessTokenDetails,
    AlexaApiError,
    AlexaApiNeedsRelinkError,
    AlexaApiNoTokenError,
)
from tests.common import extract_log_messages

if TYPE_CHECKING:
    from hass_nabucasa import Cloud
    from tests.utils.aiohttp import AiohttpClientMocker


@pytest.mark.parametrize(
    "exception,getmockargs,exception_msg",
    [
        [
            AlexaApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Failed to fetch: (500) ",
        ],
        [
            AlexaApiError,
            {"status": 429, "text": "Too fast"},
            "Failed to fetch: (429) ",
        ],
        [
            AlexaApiNeedsRelinkError,
            {"status": 400, "text": json.dumps({"reason": "RefreshTokenNotFound"})},
            "RefreshTokenNotFound",
        ],
        [
            AlexaApiError,
            {"exc": TimeoutError()},
            "Timeout reached while calling API",
        ],
        [
            AlexaApiError,
            {"exc": ClientError("boom!")},
            "Failed to fetch: boom!",
        ],
        [
            AlexaApiError,
            {"exc": Exception("boom!")},
            "Unexpected error while calling API: boom!",
        ],
    ],
)
async def test_problems_getting_access_token(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    getmockargs,
    exception_msg,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test problems getting access token."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/alexa/access_token",
        **getmockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await cloud.alexa_api.access_token()

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.parametrize(
    "response",
    [
        {
            "access_token": "test_key",
            "expires_in": 123,
            "event_endpoint": "http://example.com/events",
        }
    ],
)
async def test_getting_access_token(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    response: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test getting access token."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/alexa/access_token",
        json=response,
    )

    details = await cloud.alexa_api.access_token()

    assert details == AlexaAccessTokenDetails(**response)
    assert extract_log_messages(caplog) == snapshot


async def test_access_token_needs_relink_error(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
):
    """Test that 400 with RefreshTokenNotFound raises AlexaApiNeedsRelinkError."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/alexa/access_token",
        status=400,
        json={"reason": "RefreshTokenNotFound"},
    )

    with pytest.raises(AlexaApiNeedsRelinkError, match="RefreshTokenNotFound"):
        await cloud.alexa_api.access_token()


async def test_access_token_needs_relink_error_unknown_region(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
):
    """Test that 400 with UnknownRegion raises AlexaApiNeedsRelinkError."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/alexa/access_token",
        status=400,
        json={"reason": "UnknownRegion"},
    )

    with pytest.raises(AlexaApiNeedsRelinkError, match="UnknownRegion"):
        await cloud.alexa_api.access_token()


async def test_access_token_no_token_error(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
):
    """Test that 400 with other reasons raises AlexaApiNoTokenError."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/alexa/access_token",
        status=400,
        json={"reason": "SomeOtherReason"},
    )

    with pytest.raises(AlexaApiNoTokenError, match="No access token available"):
        await cloud.alexa_api.access_token()


async def test_access_token_no_token_error_no_reason(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
):
    """Test that 400 without reason raises AlexaApiNoTokenError."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/alexa/access_token",
        status=400,
        json={"error": "Bad Request"},
    )

    with pytest.raises(AlexaApiNoTokenError, match="No access token available"):
        await cloud.alexa_api.access_token()


async def test_access_token_raw_response_error_handling(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
):
    """Test that non-400 errors are handled correctly with raw_response=True."""
    aioclient_mock.post(
        f"https://{cloud.servicehandlers_server}/alexa/access_token",
        status=500,
        text="Internal Server Error",
    )

    with pytest.raises(AlexaApiError, match=re.escape("Failed to fetch: (500) ")):
        await cloud.alexa_api.access_token()
