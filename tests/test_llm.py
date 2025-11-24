"""Unit tests for hass_nabucasa.llm."""

from __future__ import annotations

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

import hass_nabucasa.llm as llm_module
from hass_nabucasa.llm import (
    LLM,
    LLMAuthenticationError,
    LLMImageAttachment,
    LLMRateLimitError,
    LLMServiceError,
)


def _mock_llm() -> LLM:
    cloud = MagicMock(valid_subscription=True)
    llm = LLM(cloud)
    llm._token = "token"
    llm._base_url = "https://api.example"
    llm._generate_data_model = "responses-model"
    llm._generate_image_model = "image-model"
    llm.async_ensure_token = AsyncMock()
    return llm


@pytest.mark.asyncio
async def test_async_generate_data_returns_response() -> None:
    """async_generate_data should forward parameters to LiteLLM and return response."""
    llm = _mock_llm()
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

    with patch.object(llm_module, "aresponses", mock_aresponses):
        result = await llm.async_generate_data(
            messages=[{"role": "user", "content": "hi"}],
            conversation_id="conversation-id",
            response_format={"type": "json_object"},
        )

    assert result is response
    assert mock_aresponses.await_args is not None
    kwargs = mock_aresponses.await_args.kwargs
    assert kwargs["model"] == "responses-model"
    assert kwargs["input"] == [{"role": "user", "content": "hi"}]
    assert kwargs["api_key"] == "token"
    assert kwargs["api_base"] == "https://api.example"
    assert kwargs["user"] == "conversation-id"
    assert kwargs["stream"] is False
    assert kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_async_generate_data_streams_when_requested() -> None:
    """async_generate_data should return LiteLLM stream results."""
    llm = _mock_llm()
    mock_aresponses = AsyncMock()

    with patch.object(llm_module, "aresponses", mock_aresponses):
        result = await llm.async_generate_data(
            messages=[],
            conversation_id="abc",
            stream=True,
        )

    assert result is mock_aresponses.return_value
    assert mock_aresponses.await_args.kwargs["stream"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (AuthenticationError("auth", "provider", "model"), LLMAuthenticationError),
        (RateLimitError("ratelimit", "provider", "model"), LLMRateLimitError),
        (ServiceUnavailableError("svc", "provider", "model"), LLMRateLimitError),
        (APIError(500, "api", "provider", "model"), LLMServiceError),
    ],
)
async def test_async_generate_data_maps_errors(
    raised: Exception, expected: type[Exception]
) -> None:
    """async_generate_data should convert LiteLLM errors to Cloud equivalents."""
    llm = _mock_llm()
    mock_aresponses = AsyncMock(side_effect=raised)

    with (
        patch.object(llm_module, "aresponses", mock_aresponses),
        pytest.raises(expected),
    ):
        await llm.async_generate_data(messages=[], conversation_id="conv")


@pytest.mark.asyncio
async def test_async_generate_image_without_attachments_calls_create() -> None:
    """async_generate_image should call generation helper."""
    llm = _mock_llm()
    llm._async_create_image = AsyncMock(return_value="image")
    llm._async_edit_image = AsyncMock()

    result = await llm.async_generate_image(prompt="draw")

    assert result == "image"
    llm._async_create_image.assert_awaited_once_with("draw")
    llm._async_edit_image.assert_not_called()


@pytest.mark.asyncio
async def test_async_generate_image_with_attachments_calls_edit() -> None:
    """async_generate_image should call edit helper when attachments are present."""
    llm = _mock_llm()
    llm._async_create_image = AsyncMock()
    llm._async_edit_image = AsyncMock(return_value="edited")
    attachments = [
        LLMImageAttachment(filename="pic.png",
                           mime_type="image/png", data=b"raw")
    ]

    result = await llm.async_generate_image(prompt="fix", attachments=attachments)

    assert result == "edited"
    llm._async_edit_image.assert_awaited_once_with("fix", attachments)
    llm._async_create_image.assert_not_called()


@pytest.mark.asyncio
async def test_async_edit_image_single_attachment_payload() -> None:
    """_async_edit_image should wrap a single attachment as BytesIO."""
    llm = _mock_llm()
    attachment = LLMImageAttachment(
        filename="first.png", mime_type="image/png", data=b"payload"
    )
    mock_edit = AsyncMock()
    mock_extract = AsyncMock(return_value="image")

    with (
        patch.object(llm_module, "aimage_edit", mock_edit),
        patch.object(llm_module, "_extract_response_image_data", mock_extract),
    ):
        result = await llm._async_edit_image("prompt", [attachment])

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
    llm = _mock_llm()
    attachments = [
        LLMImageAttachment(filename="base.png",
                           mime_type="image/png", data=b"base"),
        LLMImageAttachment(filename="mask.png",
                           mime_type="image/png", data=b"mask"),
        LLMImageAttachment(filename="extra.png",
                           mime_type="image/png", data=b"extra"),
    ]
    mock_edit = AsyncMock()
    mock_extract = AsyncMock(return_value="image")

    with (
        patch.object(llm_module, "aimage_edit", mock_edit),
        patch.object(llm_module, "_extract_response_image_data", mock_extract),
    ):
        result = await llm._async_edit_image("prompt", attachments)

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
    llm = _mock_llm()
    llm._generate_image_model = None

    with pytest.raises(LLMServiceError):
        await llm._async_edit_image(
            "prompt", [LLMImageAttachment(
                filename=None, mime_type=None, data=b"img")]
        )
