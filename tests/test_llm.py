"""Unit tests for hass_nabucasa.llm."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hass_nabucasa.exceptions import NabuCasaNotLoggedInError
from hass_nabucasa.llm import (
    LLMAuthenticationError,
    LLMImageAttachment,
    LLMRateLimitError,
    LLMRequestError,
    LLMResponseError,
    LLMServiceError,
    ResponsesAPIStreamEvent,
    ToolChoice,
    ToolParam,
    stream_llm_response_events,
)

if TYPE_CHECKING:
    from hass_nabucasa import Cloud

    from .utils.aiohttp import AiohttpClientMocker


class _FakeStream:
    """Simple async stream for simulating SSE responses."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") for line in lines]

    async def readline(self) -> bytes:
        if not self._lines:
            await asyncio.sleep(0)
            return b""
        return self._lines.pop(0)


class _FakeResponse:
    """Simplified ClientResponse for SSE tests."""

    def __init__(self, lines: list[str]) -> None:
        self.status = 200
        self.content = _FakeStream(lines)
        self._released = False

    def release(self) -> None:
        """Mark the response as released."""
        self._released = True

    @property
    def released(self) -> bool:
        """Return True when release() was called."""
        return self._released


@pytest.fixture(autouse=True)
def mock_llm_connection_details(aioclient_mock: AiohttpClientMocker) -> None:
    """Mock the initial LLM connection details fetch."""
    aioclient_mock.get(
        "https://api.example.com/llm/connection_details",
        json={
            "token": "token",
            "valid_until": 9999999999,
            "base_url": "https://api.example",
            "generate_data_model": "responses-model",
            "generate_image_model": "image-model",
            "conversation_model": "conv-model",
        },
    )


async def test_async_ensure_token_skips_when_not_logged_in(cloud: Cloud) -> None:
    """Ensure async_ensure_token exits early when the user is not logged in."""
    cloud.id_token = None

    with pytest.raises(NabuCasaNotLoggedInError, match="User is not logged in"):
        await cloud.llm.async_ensure_token()


async def test_async_generate_data_returns_response(cloud: Cloud) -> None:
    """async_generate_data should call the Responses API with expected payload."""
    await cloud.llm.async_ensure_token()
    messages = [{"role": "user", "content": "Hello"}]
    expected = {"output": [
        {"content": [{"type": "output_text", "text": "Hi"}]}]}
    fake_response = SimpleNamespace()
    mock_call = AsyncMock(return_value=fake_response)
    mock_get_response = AsyncMock(return_value=expected)

    with (
        patch.object(cloud.llm, "_call_llm_api", mock_call),
        patch.object(cloud.llm, "_get_response", mock_get_response),
    ):
        result = await cloud.llm.async_generate_data(
            messages=messages,
            conversation_id="conversation-id",
            response_format={"type": "json_object"},
        )

    assert result == expected
    mock_get_response.assert_awaited_once_with(fake_response)
    assert mock_call.await_args is not None
    call_payload = mock_call.await_args.kwargs["payload"]
    assert call_payload["model"] == "responses-model"
    assert call_payload["input"] == messages
    assert call_payload["conversation"] == "conversation-id"
    assert call_payload["response_format"] == {"type": "json_object"}
    assert call_payload["stream"] is False


async def test_async_generate_data_streams_when_requested(cloud: Cloud) -> None:
    """async_generate_data should return a streaming iterator when stream=True."""
    await cloud.llm.async_ensure_token()
    fake_response = _FakeResponse(
        lines=[
            'data: {"delta":"hello"}',
            "data: [DONE]",
        ]
    )
    mock_call = AsyncMock(return_value=fake_response)

    with patch.object(cloud.llm, "_call_llm_api", mock_call):
        iterator = await cloud.llm.async_generate_data(
            messages=[],
            conversation_id="conv-stream",
            stream=True,
        )

        events = [
            event.to_dict()
            async for event in cast("AsyncIterator[ResponsesAPIStreamEvent]", iterator)
        ]

    assert events == [{"delta": "hello"}]
    assert fake_response.released
    assert mock_call.await_args is not None
    payload = mock_call.await_args.kwargs["payload"]
    assert payload["stream"] is True
    assert payload["model"] == "responses-model"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, LLMAuthenticationError),
        (429, LLMRateLimitError),
        (503, LLMRateLimitError),
        (500, LLMServiceError),
    ],
)
async def test_async_generate_data_maps_http_errors(
    status: int,
    expected: type[Exception],
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """async_generate_data should translate HTTP errors to LLM errors."""
    await cloud.llm.async_ensure_token()
    aioclient_mock.post("https://api.example/responses",
                        status=status, text="err")

    with pytest.raises(expected):
        await cloud.llm.async_generate_data(messages=[], conversation_id="conv")


async def test_async_generate_image_posts_payload(cloud: Cloud) -> None:
    """async_generate_image should call the image generation endpoint."""
    await cloud.llm.async_ensure_token()
    fake_response = SimpleNamespace()
    mock_call = AsyncMock(return_value=fake_response)
    mock_get_response = AsyncMock(return_value={"data": []})
    mock_extract = AsyncMock(return_value="normalized-image")

    with (
        patch.object(cloud.llm, "_call_llm_api", mock_call),
        patch.object(cloud.llm, "_get_response", mock_get_response),
        patch.object(cloud.llm, "_extract_response_image_data", mock_extract),
    ):
        result = await cloud.llm.async_generate_image(prompt="draw a cat")

    assert result == "normalized-image"
    payload = mock_call.await_args.kwargs["payload"]
    assert payload == {"prompt": "draw a cat", "model": "image-model"}
    mock_get_response.assert_awaited_once_with(fake_response)
    mock_extract.assert_awaited_once_with({"data": []})


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, LLMAuthenticationError),
        (429, LLMRateLimitError),
        (503, LLMRateLimitError),
        (500, LLMServiceError),
    ],
)
async def test_async_generate_image_maps_http_errors(
    status: int,
    expected: type[Exception],
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """async_generate_image should translate HTTP failures."""
    await cloud.llm.async_ensure_token()
    aioclient_mock.post(
        "https://api.example/images/generations", status=status)

    with pytest.raises(expected):
        await cloud.llm.async_generate_image(prompt="draw anything")


async def test_async_edit_image_builds_file_payloads(cloud: Cloud) -> None:
    """async_edit_image should convert attachments into multipart payloads."""
    await cloud.llm.async_ensure_token()

    attachments: list[LLMImageAttachment] = [
        {"filename": "base.png", "mime_type": "image/png", "data": b"base-bytes"},
    ]

    mock_response = SimpleNamespace()
    mock_call = AsyncMock(return_value=mock_response)
    mock_get_response = AsyncMock(return_value={"data": []})
    mock_extract = AsyncMock(return_value="image-bytes")
    form_mock = MagicMock()

    with (
        patch("hass_nabucasa.llm.FormData", return_value=form_mock),
        patch.object(cloud.llm, "_call_llm_api", mock_call),
        patch.object(cloud.llm, "_get_response", mock_get_response),
        patch.object(cloud.llm, "_extract_response_image_data", mock_extract),
    ):
        result = await cloud.llm.async_edit_image(
            prompt="enhance",
            attachments=attachments,
        )

    assert result == "image-bytes"
    mock_call.assert_awaited_once()
    assert mock_call.await_args.kwargs["data"] is form_mock
    prompt_calls = [
        entry
        for entry in form_mock.add_field.mock_calls
        if entry.args[0] in {"prompt", "model"}
    ]
    assert prompt_calls[0].args == ("prompt", "enhance")
    assert prompt_calls[1].args == ("model", "image-model")

    image_calls = [
        entry for entry in form_mock.add_field.mock_calls if entry.args[0] == "image"
    ]
    image = image_calls[0]
    assert image.kwargs["filename"] == "base.png"
    assert image.kwargs["content_type"] == "image/png"
    assert image.args[1].getvalue() == b"base-bytes"


async def test_async_edit_image_requires_attachment(cloud: Cloud) -> None:
    """async_edit_image should raise when no attachments are provided."""
    await cloud.llm.async_ensure_token()

    with pytest.raises(LLMRequestError, match="No attachments provided"):
        await cloud.llm.async_edit_image(prompt="prompt", attachments=[])


async def test_async_process_conversation_returns_response(cloud: Cloud) -> None:
    """async_process_conversation should call Responses API using conversation model."""
    await cloud.llm.async_ensure_token()
    fake_response = SimpleNamespace()
    mock_call = AsyncMock(return_value=fake_response)
    mock_get_response = AsyncMock(return_value={"output": []})

    tools: list[ToolParam] = [
        {"type": "function", "function": {"name": "do_something"}},
    ]
    tool_choice: ToolChoice = {
        "type": "function",
        "function": {"name": "do_something"},
    }

    payload = [{"role": "user", "content": "Hi"}]
    with (
        patch.object(cloud.llm, "_call_llm_api", mock_call),
        patch.object(cloud.llm, "_get_response", mock_get_response),
    ):
        result = await cloud.llm.async_process_conversation(
            messages=payload,
            conversation_id="abc",
            response_format={"type": "json_schema"},
            tools=tools,
            tool_choice=tool_choice,
        )

    assert result == {"output": []}
    payload = mock_call.await_args.kwargs["payload"]
    assert payload["model"] == "conv-model"
    assert payload["tools"] == tools
    assert payload["tool_choice"] == tool_choice
    assert payload["response_format"] == {"type": "json_schema"}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, LLMAuthenticationError),
        (429, LLMRateLimitError),
        (503, LLMRateLimitError),
        (500, LLMServiceError),
    ],
)
async def test_async_process_conversation_maps_http_errors(
    status: int,
    expected: type[Exception],
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """async_process_conversation should translate HTTP errors."""
    await cloud.llm.async_ensure_token()
    aioclient_mock.post("https://api.example/responses", status=status)

    with pytest.raises(expected):
        await cloud.llm.async_process_conversation(messages=[], conversation_id="conv")


async def test_stream_llm_response_events_parses_lines() -> None:
    """stream_llm_response_events should emit valid events."""
    fake_response = _FakeResponse(
        [
            'data: {"foo": 1}\n',
            "\n",
            'data: {"bar": 2}\n',
            "\n",
            "data: [DONE]\n",
            "\n",
        ]
    )

    events = [
        event.to_dict()
        async for event in cast(
            "AsyncIterator[ResponsesAPIStreamEvent]",
            stream_llm_response_events(fake_response),
        )
    ]

    assert events == [{"foo": 1}, {"bar": 2}]
    assert fake_response.released


async def test_stream_llm_response_events_ignores_empty_events() -> None:
    """stream_llm_response_events should ignore empty (keepalive) SSE events."""
    fake_response = _FakeResponse(
        [
            "data:\n",
            "\n",
            'data: {"ok": true}\n',
            "\n",
            "data: [DONE]\n",
            "\n",
        ]
    )

    events = [
        event.to_dict()
        async for event in cast(
            "AsyncIterator[ResponsesAPIStreamEvent]",
            stream_llm_response_events(fake_response),
        )
    ]

    assert events == [{"ok": True}]
    assert fake_response.released


async def test_stream_llm_response_events_raises_on_invalid_json() -> None:
    """stream_llm_response_events should raise on invalid JSON.

    This avoids returning silently truncated output.
    """
    fake_response = _FakeResponse(
        [
            'data: {"foo": 1}\n',
            "\n",
            "data: not-json\n",
            "\n",
        ]
    )

    iterator = cast(
        "AsyncIterator[ResponsesAPIStreamEvent]",
        stream_llm_response_events(fake_response),
    )

    first_event = await anext(iterator)
    assert first_event.to_dict() == {"foo": 1}
    with pytest.raises(
        LLMResponseError, match="There was an error processing the Cloud LLM response"
    ):
        await anext(iterator)
    assert fake_response.released
