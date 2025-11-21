"""Unit tests for hass_nabucasa.ai."""

from __future__ import annotations

import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from litellm.exceptions import (
    APIError,
    AuthenticationError,
    RateLimitError,
    ServiceUnavailableError,
)
import pytest

import hass_nabucasa.ai as ai_module
from hass_nabucasa.ai import (
    Ai,
    AiAuthenticationError,
    AiImageAttachment,
    AiRateLimitError,
    AiServiceError,
    _extract_response_image_data,
    _extract_response_text,
    _flatten_text_value,
    stream_ai_text,
)


def _mock_ai() -> Ai:
    cloud = MagicMock(valid_subscription=True)
    ai = Ai(cloud)
    ai._token = "token"
    ai.base_url = "https://api.example"
    ai._generate_data_model = "responses-model"
    ai._generate_image_model = "image-model"
    ai.async_ensure_token = AsyncMock()
    return ai


def test_flatten_text_value_handles_iterables() -> None:
    """Ensure _flatten_text_value collapses supported parts."""
    payload = [
        "Hello ",
        {"text": "from "},
        SimpleNamespace(text="Ai"),
        123,
    ]

    assert _flatten_text_value(payload) == "Hello from Ai"


def test_extract_response_text_supports_namespaces() -> None:
    """_extract_response_text should handle namespace responses."""
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                content=[
                    SimpleNamespace(text="assistant text"),
                ],
            )
        ]
    )

    assert _extract_response_text(response) == {
        "role": "user",
        "content": "assistant text",
    }


@pytest.mark.asyncio
async def test_extract_response_image_data_decodes_base64() -> None:
    """Image responses with base64 payloads should decode."""
    image_bytes = b"binary"
    payload = {
        "model": "image-model",
        "data": [
            {
                "b64_json": base64.b64encode(image_bytes).decode(),
                "width": 64,
                "height": 32,
                "revised_prompt": "done",
            }
        ],
    }

    result = await _extract_response_image_data(payload)

    assert result["image_data"] == image_bytes
    assert result["mime_type"] == "image/png"
    assert result["width"] == 64
    assert result["height"] == 32
    assert result["revised_prompt"] == "done"


@pytest.mark.asyncio
async def test_extract_response_image_data_fetches_url() -> None:
    """Image responses should fetch URLs when no base64 payload exists."""
    payload = {
        "model": "image-model",
        "data": [
            {
                "url": "https://images.example/render",
                "width": 128,
                "height": 128,
            }
        ],
    }

    mock_fetch = AsyncMock(return_value=b"downloaded")
    with patch.object(ai_module, "_async_fetch_image_from_url", mock_fetch):
        result = await _extract_response_image_data(payload)

    assert result["image_data"] == b"downloaded"
    mock_fetch.assert_awaited_once_with("https://images.example/render")


@pytest.mark.asyncio
async def test_stream_ai_text_yields_initial_role() -> None:
    """stream_ai_text should emit assistant role in its first chunk."""

    async def fake_stream():
        for chunk in ("Hello", " world"):
            yield {"type": "response.output_text.delta", "delta": chunk}

    result = [chunk async for chunk in stream_ai_text(fake_stream())]

    assert result == [
        {"role": "assistant", "content": "Hello"},
        {"content": " world"},
    ]


@pytest.mark.asyncio
async def test_async_generate_data_returns_response() -> None:
    """async_generate_data should forward parameters to LiteLLM and parse responses."""
    ai = _mock_ai()
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                content=[
                    SimpleNamespace(text="Hi there"),
                ],
            )
        ]
    )
    mock_aresponses = AsyncMock(return_value=response)

    with patch.object(ai_module, "aresponses", mock_aresponses):
        result = await ai.async_generate_data(
            messages=[{"role": "user", "content": "hi"}],
            conversation_id="conversation-id",
            response_format={"type": "json_object"},
        )

    assert result == {"role": "user", "content": "Hi there"}
    assert mock_aresponses.await_args is not None
    kwargs = mock_aresponses.await_args.kwargs
    assert kwargs["model"] == "responses-model"
    assert kwargs["input"] == [{"role": "user", "content": "hi"}]
    assert kwargs["api_key"] == "token"
    assert kwargs["api_base"] == "https://api.example"
    assert kwargs["user"] == "conversation-id"
    assert kwargs["stream"] is False
    assert kwargs["text"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_async_generate_data_streams_when_requested() -> None:
    """async_generate_data should wrap LiteLLM stream results."""
    ai = _mock_ai()
    mock_aresponses = AsyncMock()
    mock_stream = MagicMock()

    with (
        patch.object(ai_module, "aresponses", mock_aresponses),
        patch.object(ai_module, "stream_ai_text", mock_stream),
    ):
        result = await ai.async_generate_data(
            messages=[],
            conversation_id="abc",
            stream=True,
        )

    assert result is mock_stream.return_value
    mock_stream.assert_called_once_with(mock_aresponses.return_value)
    assert mock_aresponses.await_args.kwargs["stream"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (AuthenticationError("auth", "provider", "model"), AiAuthenticationError),
        (RateLimitError("ratelimit", "provider", "model"), AiRateLimitError),
        (ServiceUnavailableError("svc", "provider", "model"), AiRateLimitError),
        (APIError(500, "api", "provider", "model"), AiServiceError),
    ],
)
async def test_async_generate_data_maps_errors(
    raised: Exception, expected: type[Exception]
) -> None:
    """async_generate_data should convert LiteLLM errors to Cloud equivalents."""
    ai = _mock_ai()
    mock_aresponses = AsyncMock(side_effect=raised)

    with (
        patch.object(ai_module, "aresponses", mock_aresponses),
        pytest.raises(expected),
    ):
        await ai.async_generate_data(messages=[], conversation_id="conv")


@pytest.mark.asyncio
async def test_async_generate_image_without_attachments_calls_create() -> None:
    """async_generate_image should call generation helper."""
    ai = _mock_ai()
    ai._async_create_image = AsyncMock(return_value="image")
    ai._async_edit_image = AsyncMock()

    result = await ai.async_generate_image(prompt="draw")

    assert result == "image"
    ai._async_create_image.assert_awaited_once_with("draw")
    ai._async_edit_image.assert_not_called()


@pytest.mark.asyncio
async def test_async_generate_image_with_attachments_calls_edit() -> None:
    """async_generate_image should call edit helper when attachments are present."""
    ai = _mock_ai()
    ai._async_create_image = AsyncMock()
    ai._async_edit_image = AsyncMock(return_value="edited")
    attachments = [
        AiImageAttachment(filename="pic.png", mime_type="image/png", data=b"raw")
    ]

    result = await ai.async_generate_image(prompt="fix", attachments=attachments)

    assert result == "edited"
    ai._async_edit_image.assert_awaited_once_with("fix", attachments)
    ai._async_create_image.assert_not_called()


@pytest.mark.asyncio
async def test_async_edit_image_single_attachment_payload() -> None:
    """_async_edit_image should wrap a single attachment as BytesIO."""
    ai = _mock_ai()
    attachment = AiImageAttachment(
        filename="first.png", mime_type="image/png", data=b"payload"
    )
    mock_edit = AsyncMock()
    mock_extract = AsyncMock(return_value="image")

    with (
        patch.object(ai_module, "aimage_edit", mock_edit),
        patch.object(ai_module, "_extract_response_image_data", mock_extract),
    ):
        result = await ai._async_edit_image("prompt", [attachment])

    assert result == "image"
    kwargs = mock_edit.await_args.kwargs
    assert kwargs["mask"] is None
    image_arg = kwargs["image"]
    assert isinstance(image_arg, io.BytesIO)
    assert image_arg.getvalue() == b"payload"
    assert image_arg.name == "first.png"


@pytest.mark.asyncio
async def test_async_edit_image_multiple_attachment_payloads() -> None:
    """_async_edit_image should include mask and remaining images."""
    ai = _mock_ai()
    attachments = [
        AiImageAttachment(filename="base.png", mime_type="image/png", data=b"base"),
        AiImageAttachment(filename="mask.png", mime_type="image/png", data=b"mask"),
        AiImageAttachment(filename="extra.png", mime_type="image/png", data=b"extra"),
    ]
    mock_edit = AsyncMock()
    mock_extract = AsyncMock(return_value="image")

    with (
        patch.object(ai_module, "aimage_edit", mock_edit),
        patch.object(ai_module, "_extract_response_image_data", mock_extract),
    ):
        result = await ai._async_edit_image("prompt", attachments)

    assert result == "image"
    kwargs = mock_edit.await_args.kwargs
    mask_arg = kwargs["mask"]
    assert isinstance(mask_arg, io.BytesIO)
    assert mask_arg.getvalue() == b"mask"
    image_arg = kwargs["image"]
    assert isinstance(image_arg, list)
    assert [part.getvalue() for part in image_arg] == [b"base", b"extra"]


@pytest.mark.asyncio
async def test_async_edit_image_requires_model() -> None:
    """_async_edit_image should fail when the model is missing."""
    ai = _mock_ai()
    ai._generate_image_model = None

    with pytest.raises(AiServiceError):
        await ai._async_edit_image(
            "prompt", [AiImageAttachment(filename=None, mime_type=None, data=b"img")]
        )
