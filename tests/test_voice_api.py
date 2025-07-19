"""Test the voice connection details API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiohttp import ClientError
import pytest

from hass_nabucasa.voice_api import (
    VoiceApi,
    VoiceApiError,
    VoiceConnectionDetails,
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
            VoiceApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for get from example.com/voice/connection_details (500)",
            "Failed to parse API response",
        ],
        [
            VoiceApiError,
            {"status": 429, "text": "Too fast"},
            "Response for get from example.com/voice/connection_details (429)",
            "Failed to parse API response",
        ],
        [
            VoiceApiError,
            {"exc": TimeoutError()},
            "",
            "Timeout reached while calling API",
        ],
        [
            VoiceApiError,
            {"exc": ClientError("boom!")},
            "",
            "Failed to fetch: boom!",
        ],
        [
            VoiceApiError,
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
    voice_api = VoiceApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/voice/connection_details",
        **getmockargs,
    )

    with pytest.raises(exception, match=exception_msg):
        await voice_api.connection_details()

    if log_msg:
        assert log_msg in caplog.text


@pytest.mark.parametrize(
    "response",
    [
        {
            "valid": "123456789",
            "authorized_key": "test_key",
            "endpoint_stt": "http://example.com/stt",
            "endpoint_tts": "http://example.com/tts",
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
    voice_api = VoiceApi(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/voice/connection_details",
        json=response,
    )

    details = await voice_api.connection_details()

    assert details == VoiceConnectionDetails(**response)
    assert (
        "Response for get from example.com/voice/connection_details (200)"
        in caplog.text
    )
