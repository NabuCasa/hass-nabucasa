"""Test the voice connection details API."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError
import pytest

from hass_nabucasa.alexa_api import (
    AlexaAccessTokenDetails,
    AlexaApi,
    AlexaApiError,
    AlexaApiNeedsRelinkError,
    AlexaApiNoTokenError,
)

if TYPE_CHECKING:
    from hass_nabucasa import Cloud
    from tests.utils.aiohttp import AiohttpClientMocker

API_HOSTNAME = "example.com"


@pytest.fixture(autouse=True)
def set_hostname(auth_cloud_mock):
    """Set API hostname for the mock cloud service."""
    auth_cloud_mock.servicehandlers_server = API_HOSTNAME


@pytest.mark.parametrize(
    "exception,getmockargs,log_msg,exception_msg",
    [
        [
            AlexaApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for post from example.com/alexa/access_token (500)",
            "Failed to fetch: (500) ",
        ],
        [
            AlexaApiError,
            {"status": 429, "text": "Too fast"},
            "Response for post from example.com/alexa/access_token (429)",
            "Failed to fetch: (429) ",
        ],
        [
            AlexaApiNeedsRelinkError,
            {"status": 400, "text": json.dumps({"reason": "RefreshTokenNotFound"})},
            "Response for post from example.com/alexa/access_token (400) "
            "RefreshTokenNotFound",
            "RefreshTokenNotFound",
        ],
        [
            AlexaApiError,
            {"exc": TimeoutError()},
            "",
            "Timeout reached while calling API",
        ],
        [
            AlexaApiError,
            {"exc": ClientError("boom!")},
            "",
            "Failed to fetch: boom!",
        ],
        [
            AlexaApiError,
            {"exc": Exception("boom!")},
            "",
            "Unexpected error while calling API: boom!",
        ],
    ],
)
async def test_problems_getting_caccess_token(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    getmockargs,
    log_msg,
    exception_msg,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems getting access token."""
    alexa_api = AlexaApi(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/alexa/access_token",
        **getmockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await alexa_api.access_token()

    if log_msg:
        assert log_msg in caplog.text


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
    auth_cloud_mock: Cloud,
    response: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test getting access token."""
    alexa_api = AlexaApi(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/alexa/access_token",
        json=response,
    )

    details = await alexa_api.access_token()

    assert details == AlexaAccessTokenDetails(**response)
    assert "Response for post from example.com/alexa/access_token (200)" in caplog.text


async def test_access_token_needs_relink_error(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
):
    """Test that 400 with RefreshTokenNotFound raises AlexaApiNeedsRelinkError."""
    alexa_api = AlexaApi(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/alexa/access_token",
        status=400,
        json={"reason": "RefreshTokenNotFound"},
    )

    with pytest.raises(AlexaApiNeedsRelinkError, match="RefreshTokenNotFound"):
        await alexa_api.access_token()


async def test_access_token_needs_relink_error_unknown_region(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
):
    """Test that 400 with UnknownRegion raises AlexaApiNeedsRelinkError."""
    alexa_api = AlexaApi(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/alexa/access_token",
        status=400,
        json={"reason": "UnknownRegion"},
    )

    with pytest.raises(AlexaApiNeedsRelinkError, match="UnknownRegion"):
        await alexa_api.access_token()


async def test_access_token_no_token_error(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
):
    """Test that 400 with other reasons raises AlexaApiNoTokenError."""
    alexa_api = AlexaApi(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/alexa/access_token",
        status=400,
        json={"reason": "SomeOtherReason"},
    )

    with pytest.raises(AlexaApiNoTokenError, match="No access token available"):
        await alexa_api.access_token()


async def test_access_token_no_token_error_no_reason(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
):
    """Test that 400 without reason raises AlexaApiNoTokenError."""
    alexa_api = AlexaApi(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/alexa/access_token",
        status=400,
        json={"error": "Bad Request"},
    )

    with pytest.raises(AlexaApiNoTokenError, match="No access token available"):
        await alexa_api.access_token()


async def test_access_token_raw_response_error_handling(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
):
    """Test that non-400 errors are handled correctly with raw_response=True."""
    alexa_api = AlexaApi(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/alexa/access_token",
        status=500,
        text="Internal Server Error",
    )

    with pytest.raises(AlexaApiError, match=re.escape("Failed to fetch: (500) ")):
        await alexa_api.access_token()
