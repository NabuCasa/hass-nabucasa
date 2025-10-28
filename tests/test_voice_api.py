"""Test the voice connection details API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiohttp import ClientError
import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa.voice_api import (
    VoiceApiError,
    VoiceConnectionDetails,
)
from tests.common import extract_log_messages

if TYPE_CHECKING:
    from hass_nabucasa import Cloud
    from tests.utils.aiohttp import AiohttpClientMocker


@pytest.mark.parametrize(
    "exception,getmockargs,exception_msg",
    [
        [
            VoiceApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Failed to parse API response",
        ],
        [
            VoiceApiError,
            {"status": 429, "text": "Too fast"},
            "Failed to parse API response",
        ],
        [
            VoiceApiError,
            {"exc": TimeoutError()},
            "Timeout reached while calling API",
        ],
        [
            VoiceApiError,
            {"exc": ClientError("boom!")},
            "Failed to fetch: boom!",
        ],
        [
            VoiceApiError,
            {"exc": Exception("boom!")},
            "Unexpected error while calling API: boom!",
        ],
    ],
)
async def test_problems_getting_connection_details(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    getmockargs,
    exception_msg,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test problems getting connection details."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/voice/connection_details",
        **getmockargs,
    )

    with pytest.raises(exception, match=exception_msg):
        await cloud.voice_api.connection_details()

    assert extract_log_messages(caplog) == snapshot


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
    cloud: Cloud,
    response: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test getting connection details."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/voice/connection_details",
        json=response,
    )

    details = await cloud.voice_api.connection_details()

    assert details == VoiceConnectionDetails(**response)
    assert extract_log_messages(caplog) == snapshot
