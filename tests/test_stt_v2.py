"""Test the speech to text module."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from aiohttp import WSMessage, WSMsgType, client_exceptions
import pytest

from hass_nabucasa import Cloud
from hass_nabucasa.exceptions import CloudError
from hass_nabucasa.service_discovery import VALID_ACTION_NAMES
from hass_nabucasa.stt_v2 import (
    SpeechToTextV2,
    SpeechToTextV2ConnectionError,
    SpeechToTextV2Error,
    SpeechToTextV2UnsupportedLanguageError,
)

from .utils.aiohttp import AiohttpClientMocker


class MockWebSocket:
    """Mock websocket replaying one group of messages per session."""

    def __init__(self, *sessions: list[WSMessage]) -> None:
        """Initialize the mock websocket."""
        self.closed = False
        self.sent_json: list[dict[str, Any]] = []
        self.sent_bytes: list[bytes] = []
        self._sessions = list(sessions)
        self._available: list[WSMessage] = []
        self._wake = asyncio.Event()

    async def send_json(self, data: dict[str, Any]) -> None:
        """Record a JSON frame and release the responses of a new session."""
        self.sent_json.append(data)
        if data.get("type") != "stop_session" and self._sessions:
            self._available.extend(self._sessions.pop(0))
            self._wake.set()

    async def send_bytes(self, data: bytes) -> None:
        """Record a binary frame."""
        self.sent_bytes.append(data)

    async def receive(self) -> WSMessage:
        """Return the next released message, or block while idle."""
        while not self._available:
            self._wake.clear()
            await self._wake.wait()
            if self.closed:
                return WSMessage(WSMsgType.CLOSED, None, None)
        return self._available.pop(0)

    async def close(self) -> None:
        """Close the websocket."""
        self.closed = True
        self._wake.set()


def text_message(data: dict[str, Any]) -> WSMessage:
    """Return a websocket text message holding JSON."""
    return WSMessage(WSMsgType.TEXT, json.dumps(data), None)


async def audio_stream(*chunks: bytes) -> AsyncIterable[bytes]:
    """Yield the given audio chunks."""
    for chunk in chunks:
        yield chunk


@pytest.fixture(name="prefill_service_discovery_cache")
def prefill_service_discovery_cache_fixture() -> bool:
    """Start without a service discovery cache, so the mocked endpoint is used."""
    return False


@pytest.fixture(name="stt")
def stt_fixture(
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
    service_discovery_fixture_data: dict[str, Any],
) -> SpeechToTextV2:
    """Return a speech to text instance with service discovery mocked."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/.well-known/service-discovery",
        json={
            **service_discovery_fixture_data,
            "actions": {
                **{
                    action: f"https://api.example.com/{action}"
                    for action in VALID_ACTION_NAMES
                },
                **service_discovery_fixture_data["actions"],
            },
        },
    )
    return SpeechToTextV2(cloud)


def connect_returns(stt: SpeechToTextV2, *websockets: MockWebSocket) -> None:
    """Make ws_connect return the given websockets in order."""
    stt.cloud.websession.ws_connect = AsyncMock(side_effect=list(websockets))


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en-US", "en"),
        ("en", "en"),
        ("EN-GB", "en"),
        ("zh-HK", "zh"),
        ("nb-NO", "no"),
        ("fil-PH", "tl"),
        ("hy-AM", None),
        ("wuu-CN", None),
    ],
)
def test_resolve_language(language: str, expected: str | None) -> None:
    """Test that locales map to the language codes of the service."""
    assert SpeechToTextV2.resolve_language(language) == expected


async def test_process_stt(stt: SpeechToTextV2) -> None:
    """Test a successful transcription."""
    websocket = MockWebSocket(
        [
            text_message(
                {"type": "session_ended", "reason": "finished", "transcript": "Hi"}
            )
        ]
    )
    connect_returns(stt, websocket)

    response = await stt.process_stt(
        stream=audio_stream(b"\x01\x02", b"\x03\x04"),
        language="en-US",
        audio_format="wav",
        codec="pcm",
        bit_rate=16,
        sample_rate=16000,
        channel=1,
    )

    assert response.success is True
    assert response.text == "Hi"
    assert websocket.sent_json[0] == {
        "language": "en",
        "format": "wav",
        "codec": "pcm",
        "bit_rate": 16,
        "sample_rate": 16000,
        "channel": 1,
        "options": {"endpointing": True},
    }
    assert websocket.sent_json[1] == {"type": "stop_session"}
    assert websocket.sent_bytes == [b"\x01\x02", b"\x03\x04"]

    await stt.disconnect()


async def test_process_stt_without_speech(stt: SpeechToTextV2) -> None:
    """Test that a session without a transcript is not a success."""
    connect_returns(
        stt,
        MockWebSocket([text_message({"type": "session_ended", "reason": "finished"})]),
    )

    response = await stt.process_stt(
        stream=audio_stream(b"\x01\x02"),
        language="en-US",
        audio_format="wav",
        codec="pcm",
        bit_rate=16,
        sample_rate=16000,
        channel=1,
    )

    assert response.success is False
    assert response.text is None

    await stt.disconnect()


async def test_process_stt_unsupported_language(stt: SpeechToTextV2) -> None:
    """Test that an unsupported language is rejected before connecting."""
    connect_returns(stt, MockWebSocket())

    with pytest.raises(
        SpeechToTextV2UnsupportedLanguageError,
        match="Language hy-AM not supported",
    ):
        await stt.process_stt(
            stream=audio_stream(b"\x01\x02"),
            language="hy-AM",
            audio_format="wav",
            codec="pcm",
            bit_rate=16,
            sample_rate=16000,
            channel=1,
        )

    stt.cloud.websession.ws_connect.assert_not_called()


@pytest.mark.parametrize(
    ("messages", "error", "match"),
    [
        (
            [text_message({"type": "session_ended", "reason": "timeout"})],
            SpeechToTextV2Error,
            "Session ended with reason: timeout",
        ),
        (
            [text_message({"type": "error", "error": "boom"})],
            SpeechToTextV2Error,
            "boom",
        ),
        (
            [text_message({"error": "legacy boom"})],
            SpeechToTextV2Error,
            "legacy boom",
        ),
        (
            [WSMessage(WSMsgType.TEXT, "not json", None)],
            SpeechToTextV2Error,
            "Invalid JSON in message",
        ),
        (
            [WSMessage(WSMsgType.CLOSE, None, None)],
            SpeechToTextV2ConnectionError,
            "Connection lost: CLOSE",
        ),
        (
            [WSMessage(WSMsgType.BINARY, b"nope", None)],
            SpeechToTextV2Error,
            "Unexpected message type: BINARY",
        ),
    ],
    ids=[
        "bad-reason",
        "error-type",
        "legacy-error",
        "invalid-json",
        "closed",
        "binary",
    ],
)
async def test_process_stt_errors(
    stt: SpeechToTextV2,
    messages: list[WSMessage],
    error: type[Exception],
    match: str,
) -> None:
    """Test that terminal error responses raise."""
    websocket = MockWebSocket(messages)
    connect_returns(stt, websocket)

    with pytest.raises(error, match=match):
        await stt.process_stt(
            stream=audio_stream(b"\x01\x02"),
            language="en-US",
            audio_format="wav",
            codec="pcm",
            bit_rate=16,
            sample_rate=16000,
            channel=1,
        )

    assert websocket.closed is True


async def test_process_stt_ignores_non_terminal_messages(stt: SpeechToTextV2) -> None:
    """Test that partial results are ignored."""
    connect_returns(
        stt,
        MockWebSocket(
            [
                text_message({"type": "partial", "transcript": "H"}),
                text_message(
                    {"type": "session_ended", "reason": "finished", "transcript": "Hi"}
                ),
            ]
        ),
    )

    response = await stt.process_stt(
        stream=audio_stream(b"\x01\x02"),
        language="en-US",
        audio_format="wav",
        codec="pcm",
        bit_rate=16,
        sample_rate=16000,
        channel=1,
    )

    assert response.text == "Hi"

    await stt.disconnect()


async def test_process_stt_realigns_pcm_frames(stt: SpeechToTextV2) -> None:
    """Test that PCM samples stay aligned across chunk boundaries."""
    websocket = MockWebSocket(
        [
            text_message(
                {"type": "session_ended", "reason": "finished", "transcript": "Hi"}
            )
        ]
    )
    connect_returns(stt, websocket)

    await stt.process_stt(
        stream=audio_stream(b"\x01\x02\x03", b"\x04"),
        language="en-US",
        audio_format="wav",
        codec="pcm",
        bit_rate=16,
        sample_rate=16000,
        channel=1,
    )

    assert websocket.sent_bytes == [b"\x01\x02", b"\x03\x04"]

    await stt.disconnect()


async def test_process_stt_incomplete_pcm_frame(stt: SpeechToTextV2) -> None:
    """Test that a truncated PCM stream raises."""
    websocket = MockWebSocket(
        [
            text_message(
                {"type": "session_ended", "reason": "finished", "transcript": "Hi"}
            )
        ]
    )
    connect_returns(stt, websocket)

    with pytest.raises(SpeechToTextV2Error, match="Incomplete PCM audio frame"):
        await stt.process_stt(
            stream=audio_stream(b"\x01\x02\x03"),
            language="en-US",
            audio_format="wav",
            codec="pcm",
            bit_rate=16,
            sample_rate=16000,
            channel=1,
        )

    assert websocket.closed is True


async def test_process_stt_keeps_opus_chunks_intact(stt: SpeechToTextV2) -> None:
    """Test that non-PCM audio is forwarded unchanged."""
    websocket = MockWebSocket(
        [
            text_message(
                {"type": "session_ended", "reason": "finished", "transcript": "Hi"}
            )
        ]
    )
    connect_returns(stt, websocket)

    await stt.process_stt(
        stream=audio_stream(b"\x01\x02\x03"),
        language="en-US",
        audio_format="ogg",
        codec="opus",
        bit_rate=16,
        sample_rate=16000,
        channel=1,
    )

    assert websocket.sent_bytes == [b"\x01\x02\x03"]

    await stt.disconnect()


async def test_process_stt_reuses_connection(stt: SpeechToTextV2) -> None:
    """Test that a second request reuses the open connection."""
    connect_returns(
        stt,
        MockWebSocket(
            [
                text_message(
                    {"type": "session_ended", "reason": "finished", "transcript": "A"}
                )
            ],
            [
                text_message(
                    {"type": "session_ended", "reason": "finished", "transcript": "B"}
                )
            ],
        ),
    )

    for expected in ("A", "B"):
        response = await stt.process_stt(
            stream=audio_stream(b"\x01\x02"),
            language="en-US",
            audio_format="wav",
            codec="pcm",
            bit_rate=16,
            sample_rate=16000,
            channel=1,
        )
        assert response.text == expected

    assert stt.cloud.websession.ws_connect.call_count == 1

    await stt.disconnect()


async def test_process_stt_reconnects_after_failure(stt: SpeechToTextV2) -> None:
    """Test that a dropped connection is re-established on the next request."""
    connect_returns(
        stt,
        MockWebSocket([WSMessage(WSMsgType.CLOSE, None, None)]),
        MockWebSocket(
            [
                text_message(
                    {"type": "session_ended", "reason": "finished", "transcript": "B"}
                )
            ]
        ),
    )

    with pytest.raises(SpeechToTextV2ConnectionError):
        await stt.process_stt(
            stream=audio_stream(b"\x01\x02"),
            language="en-US",
            audio_format="wav",
            codec="pcm",
            bit_rate=16,
            sample_rate=16000,
            channel=1,
        )

    response = await stt.process_stt(
        stream=audio_stream(b"\x01\x02"),
        language="en-US",
        audio_format="wav",
        codec="pcm",
        bit_rate=16,
        sample_rate=16000,
        channel=1,
    )

    assert response.text == "B"
    assert stt.cloud.websession.ws_connect.call_count == 2

    await stt.disconnect()


async def test_connect_uses_cloud_token(stt: SpeechToTextV2) -> None:
    """Test that the connection is authorized with a refreshed Cognito token."""
    connect_returns(stt, MockWebSocket())

    await stt.connect()

    call = stt.cloud.websession.ws_connect.call_args
    assert call.args[0] == "wss://stt-proxy.example.com/websocket"
    assert call.kwargs["headers"]["Authorization"] == f"Bearer {stt.cloud.id_token}"
    stt.cloud.auth.async_check_token.assert_awaited_once()

    await stt.disconnect()


async def test_connect_token_refresh_error(stt: SpeechToTextV2) -> None:
    """Test that a failing token refresh raises."""
    stt.cloud.auth.async_check_token = AsyncMock(side_effect=CloudError("expired"))
    connect_returns(stt, MockWebSocket())

    with pytest.raises(SpeechToTextV2ConnectionError, match="token refresh failure"):
        await stt.connect()

    stt.cloud.websession.ws_connect.assert_not_called()


async def test_connect_while_logged_out(stt: SpeechToTextV2) -> None:
    """Test that connecting without a token raises."""
    stt.cloud.id_token = None
    connect_returns(stt, MockWebSocket())

    with pytest.raises(SpeechToTextV2ConnectionError, match="logged out"):
        await stt.connect()

    stt.cloud.websession.ws_connect.assert_not_called()


async def test_connect_error(stt: SpeechToTextV2) -> None:
    """Test that a failing connection raises."""
    stt.cloud.websession.ws_connect = AsyncMock(
        side_effect=client_exceptions.ClientError("no route")
    )

    with pytest.raises(SpeechToTextV2ConnectionError, match="Unable to connect"):
        await stt.connect()


async def test_connect_and_disconnect(stt: SpeechToTextV2) -> None:
    """Test that connecting up front keeps the connection available."""
    websocket = MockWebSocket(
        [
            text_message(
                {"type": "session_ended", "reason": "finished", "transcript": "Hi"}
            )
        ]
    )
    connect_returns(stt, websocket)

    await stt.connect()

    response = await stt.process_stt(
        stream=audio_stream(b"\x01\x02"),
        language="en-US",
        audio_format="wav",
        codec="pcm",
        bit_rate=16,
        sample_rate=16000,
        channel=1,
    )

    assert response.text == "Hi"
    assert stt.cloud.websession.ws_connect.call_count == 1

    await stt.disconnect()
    assert websocket.closed is True


async def test_connect_twice_keeps_connection(stt: SpeechToTextV2) -> None:
    """Test that connecting again reuses the open connection."""
    websocket = MockWebSocket()
    connect_returns(stt, websocket)

    await stt.connect()
    await stt.connect()

    assert stt.cloud.websession.ws_connect.call_count == 1
    assert websocket.closed is False

    await stt.disconnect()
    assert websocket.closed is True


async def test_disconnect_without_connection(stt: SpeechToTextV2) -> None:
    """Test that disconnecting while idle is a no-op."""
    await stt.disconnect()


async def test_registers_on_stop(cloud_mock: MagicMock) -> None:
    """Test that the connection is closed when the cloud stops."""
    cloud_mock.register_on_stop = MagicMock()
    stt = SpeechToTextV2(cloud_mock)

    cloud_mock.register_on_stop.assert_called_once_with(stt.disconnect)
