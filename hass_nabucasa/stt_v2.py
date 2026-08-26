"""Speech to text over a persistent WebSocket connection."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
from aiohttp.hdrs import AUTHORIZATION, USER_AGENT

from .exceptions import CloudError, NabuCasaBaseError
from .voice import STTResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterable

    from . import Cloud, _ClientT


_LOGGER = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 300

# Max time to wait for a terminal session response (partial messages may precede it).
RECEIVE_TERMINAL_RESPONSE_TIMEOUT = 600

STT_V2_LANGUAGES = [
    "af",
    "ar",
    "az",
    "be",
    "bg",
    "bn",
    "bs",
    "ca",
    "cs",
    "cy",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "eu",
    "fa",
    "fi",
    "fr",
    "gl",
    "gu",
    "he",
    "hi",
    "hr",
    "hu",
    "id",
    "it",
    "ja",
    "kk",
    "kn",
    "ko",
    "lt",
    "lv",
    "mk",
    "ml",
    "mr",
    "ms",
    "nl",
    "no",
    "pa",
    "pl",
    "pt",
    "ro",
    "ru",
    "sk",
    "sl",
    "sq",
    "sr",
    "sv",
    "sw",
    "ta",
    "te",  # codespell:ignore
    "th",
    "tl",
    "tr",
    "uk",
    "ur",
    "vi",
    "zh",
]

CLOSE_MESSAGE_TYPES = (
    aiohttp.WSMsgType.CLOSE,
    aiohttp.WSMsgType.CLOSED,
    aiohttp.WSMsgType.CLOSING,
    aiohttp.WSMsgType.ERROR,
)

# Base codes that this service spells differently than the Azure locales do.
LANGUAGE_ALIASES = {"fil": "tl", "nb": "no"}


class SpeechToTextV2Error(NabuCasaBaseError):
    """General speech to text error."""


class SpeechToTextV2ConnectionError(SpeechToTextV2Error):
    """Error connecting to the speech to text service."""


class SpeechToTextV2UnsupportedLanguageError(SpeechToTextV2Error):
    """Error raised when the requested language is not supported."""


class SpeechToTextV2:
    """Speech to text over a persistent WebSocket connection."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize speech to text."""
        self.cloud = cloud
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session_lock = asyncio.Lock()
        self._idle_task: asyncio.Task[None] | None = None

        cloud.register_on_stop(self.disconnect)

    @staticmethod
    def resolve_language(language: str) -> str | None:
        """Return the service language for a locale, or None if unsupported."""
        base = language.split("-", maxsplit=1)[0].lower()
        base = LANGUAGE_ALIASES.get(base, base)
        return base if base in STT_V2_LANGUAGES else None

    async def connect(self) -> None:
        """Open the WebSocket connection to the speech to text service."""
        async with self._session_lock:
            await self._stop_idle_listener()
            if self._ws is None or self._ws.closed:
                await self._connect_ws()
            self._start_idle_listener()

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        async with self._session_lock:
            await self._stop_idle_listener()
            await self._close_ws()
        _LOGGER.debug("Disconnected from speech to text service")

    async def process_stt(
        self,
        *,
        stream: AsyncIterable[bytes],
        language: str,
        audio_format: str,
        codec: str,
        bit_rate: int,
        sample_rate: int,
        channel: int,
    ) -> STTResponse:
        """Run a transcription session on the persistent connection.

        Reconnects automatically when the connection was closed in between.
        """
        if (service_language := self.resolve_language(language)) is None:
            raise SpeechToTextV2UnsupportedLanguageError(
                f"Language {language} not supported"
            )

        async with self._session_lock:
            await self._stop_idle_listener()

            try:
                if self._ws is None or self._ws.closed:
                    await self._connect_ws()
                text = await self._run_session(
                    language=service_language,
                    audio_format=audio_format,
                    codec=codec,
                    bit_rate=bit_rate,
                    sample_rate=sample_rate,
                    channel=channel,
                    stream=stream,
                )
            except aiohttp.ClientError as err:
                raise SpeechToTextV2ConnectionError(
                    f"Unable to send audio due to {err}"
                ) from err
            finally:
                if self._ws is not None and not self._ws.closed:
                    self._start_idle_listener()

        return STTResponse(text is not None, text)

    async def _async_authorization_token(self) -> str:
        """Return the token that authorizes the connection."""
        try:
            await self.cloud.auth.async_check_token()
        except CloudError as err:
            raise SpeechToTextV2ConnectionError(
                f"Unable to connect due to token refresh failure: {err}"
            ) from err

        if self.cloud.id_token is None:
            raise SpeechToTextV2ConnectionError("Unable to connect while logged out")

        return self.cloud.id_token

    async def _connect_ws(self) -> None:
        """Open the raw WebSocket connection."""
        token = await self._async_authorization_token()
        try:
            websocket_uri = await self.cloud.service_discovery.async_action_url(
                "stt_proxy_websocket"
            )
        except CloudError as err:
            raise SpeechToTextV2ConnectionError(
                f"Unable to connect due to service discovery failure: {err}"
            ) from err
        try:
            self._ws = await self.cloud.websession.ws_connect(
                websocket_uri,
                headers={
                    AUTHORIZATION: f"Bearer {token}",
                    USER_AGENT: self.cloud.client.client_name,
                },
                heartbeat=HEARTBEAT_INTERVAL,
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SpeechToTextV2ConnectionError(
                f"Unable to connect due to {err}"
            ) from err

        _LOGGER.debug("Connected to speech to text service at %s", websocket_uri)

    def _start_idle_listener(self) -> None:
        """Start a background task that monitors for connection drops."""
        self._idle_task = asyncio.create_task(self._idle_listen())

    async def _stop_idle_listener(self) -> None:
        """Cancel and await the idle listener task."""
        if self._idle_task is not None and not self._idle_task.done():
            self._idle_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._idle_task
        self._idle_task = None

    async def _idle_listen(self) -> None:
        """Wait for a message while idle; any frame indicates a problem."""
        assert self._ws is not None

        try:
            received = await self._ws.receive()
        except asyncio.CancelledError:
            return
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error on speech to text WebSocket")
        else:
            if received.type in CLOSE_MESSAGE_TYPES:
                _LOGGER.debug("Speech to text connection closed while idle")
            else:
                _LOGGER.warning(
                    "Unexpected message from speech to text service while idle: %s",
                    received.type.name,
                )

        await self._close_ws()

    async def _close_ws(self) -> None:
        """Close the current WebSocket and drop the reference."""
        if self._ws is not None and not self._ws.closed:
            with contextlib.suppress(aiohttp.ClientError):
                await self._ws.close()
        self._ws = None

    async def _run_session(
        self,
        *,
        language: str,
        audio_format: str,
        codec: str,
        bit_rate: int,
        sample_rate: int,
        channel: int,
        stream: AsyncIterable[bytes],
    ) -> str | None:
        """Execute the send/receive session protocol.

        The WebSocket is closed when the session is interrupted, so the next
        call starts from a guaranteed-clean connection.
        """
        assert self._ws is not None

        await self._ws.send_json(
            {
                "language": language,
                "format": audio_format,
                "codec": codec,
                "bit_rate": bit_rate,
                "sample_rate": sample_rate,
                "channel": channel,
                "options": {"endpointing": True},
            }
        )

        receive_task = asyncio.create_task(self._receive_terminal_response())

        try:
            return self._handle_session_ended(
                await self._stream_audio(receive_task, stream, codec)
            )
        except BaseException:  # pylint: disable=broad-except
            await self._dispose_receive_task(receive_task)
            await self._close_ws()
            raise

    async def _stream_audio(
        self,
        receive_task: asyncio.Task[dict[str, Any]],
        stream: AsyncIterable[bytes],
        codec: str,
    ) -> dict[str, Any]:
        """Send the audio stream and return the terminal response."""
        assert self._ws is not None

        chunk_buffer = bytearray()
        is_pcm = codec == "pcm"
        stream_exhausted = True

        async for stream_chunk in stream:
            if receive_task.done():
                stream_exhausted = False
                break

            audio_chunk = stream_chunk
            if is_pcm:
                # Keep PCM samples aligned to 16-bit frames across chunk
                # boundaries instead of silently dropping trailing bytes.
                chunk_buffer.extend(stream_chunk)
                if len(chunk_buffer) % 2 != 0:
                    audio_chunk = bytes(chunk_buffer[:-1])
                    chunk_buffer = bytearray(chunk_buffer[-1:])
                else:
                    audio_chunk = bytes(chunk_buffer)
                    chunk_buffer = bytearray()

            if audio_chunk:
                await self._ws.send_bytes(audio_chunk)

        if is_pcm and stream_exhausted and chunk_buffer:
            raise SpeechToTextV2Error("Incomplete PCM audio frame received from stream")

        if not receive_task.done():
            await self._ws.send_json({"type": "stop_session"})

        return await receive_task

    @staticmethod
    async def _dispose_receive_task(receive_task: asyncio.Task[dict[str, Any]]) -> None:
        """Cancel and drain the receive task without hiding the original failure."""
        if not receive_task.done():
            receive_task.cancel()

        with contextlib.suppress(asyncio.CancelledError, Exception):
            await receive_task

    @staticmethod
    def _handle_session_ended(response: dict[str, Any]) -> str | None:
        """Extract the transcript from a terminal response."""
        match response:
            case {"type": "session_ended", "reason": reason, **rest}:
                if reason != "finished":
                    raise SpeechToTextV2Error(f"Session ended with reason: {reason}")
                transcript = rest.get("transcript")
                _LOGGER.debug("Transcription complete")
                return transcript
            case {"type": "error", "error": error} | {"error": error}:
                raise SpeechToTextV2Error(str(error))
            case _:
                raise SpeechToTextV2Error(f"Unexpected response: {response}")

    async def _receive_terminal_response(self) -> dict[str, Any]:
        """Receive messages until a terminal session response is received."""
        try:
            async with asyncio.timeout(RECEIVE_TERMINAL_RESPONSE_TIMEOUT):
                while True:
                    response = await self._receive_json()

                    if self._is_terminal_response(response):
                        return response

                    _LOGGER.debug("Ignoring non-terminal message: %s", response)
        except TimeoutError as err:
            raise SpeechToTextV2ConnectionError(
                "Timed out waiting for terminal response"
            ) from err

    @staticmethod
    def _is_terminal_response(response: dict[str, Any]) -> bool:
        """Return True when the response ends the current session."""
        match response:
            case {"type": "session_ended"} | {"type": "error"} | {"error": _}:
                return True
            case _:
                return False

    async def _receive_json(self) -> dict[str, Any]:
        """Receive a JSON text frame from the WebSocket."""
        assert self._ws is not None

        received = await self._ws.receive()

        if received.type == aiohttp.WSMsgType.TEXT:
            try:
                return received.json()  # type: ignore[no-any-return]
            except ValueError as err:
                raise SpeechToTextV2Error(
                    f"Invalid JSON in message: {received.data!r}"
                ) from err

        if received.type in CLOSE_MESSAGE_TYPES:
            raise SpeechToTextV2ConnectionError(
                f"Connection lost: {received.type.name}"
            )

        raise SpeechToTextV2Error(f"Unexpected message type: {received.type.name}")
