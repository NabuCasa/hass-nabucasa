"""Unit tests for hass_nabucasa.llm."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, patch

from litellm import ToolChoice, ToolParam
from litellm.exceptions import (
    APIError,
    AuthenticationError,
    RateLimitError,
    ServiceUnavailableError,
)
import pytest

from hass_nabucasa.exceptions import NabuCasaNotLoggedInError
from hass_nabucasa.llm import (
    LLMAuthenticationError,
    LLMImageAttachment,
    LLMRateLimitError,
    LLMServiceError,
)

if TYPE_CHECKING:
    from hass_nabucasa import Cloud


@pytest.fixture(autouse=True)
def mock_llm_connection_details(aioclient_mock):
    """Mock LLM connection details API call for all tests."""
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
    with (
        patch(
            "hass_nabucasa.Cloud.is_logged_in",
            False,
        ),
        pytest.raises(NabuCasaNotLoggedInError, match="User is not logged in"),
    ):
        await cloud.llm.async_ensure_token()


async def test_async_generate_data_returns_response(cloud: Cloud) -> None:
    """async_generate_data should forward parameters to LiteLLM and return response."""
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

    with patch("hass_nabucasa.llm.aresponses", mock_aresponses):
        result = await cloud.llm.async_generate_data(
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
    assert kwargs["text_format"] == {"type": "json_object"}


async def test_async_generate_data_streams_when_requested(cloud: Cloud) -> None:
    """async_generate_data should return LiteLLM stream results."""
    mock_aresponses = AsyncMock()

    with patch("hass_nabucasa.llm.aresponses", mock_aresponses):
        result = await cloud.llm.async_generate_data(
            messages=[],
            conversation_id="abc",
            stream=True,
        )

    assert result is mock_aresponses.return_value
    assert mock_aresponses.await_args.kwargs["stream"] is True


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
    raised: Exception,
    expected: type[Exception],
    cloud: Cloud,
) -> None:
    """async_generate_data should convert LiteLLM errors to Cloud equivalents."""
    mock_aresponses = AsyncMock(side_effect=raised)

    with (
        patch("hass_nabucasa.llm.aresponses", mock_aresponses),
        pytest.raises(expected),
    ):
        await cloud.llm.async_generate_data(messages=[], conversation_id="conv")


async def test_async_generate_image_calls_aimage_generation(
    cloud: Cloud, mock_llm_connection_details
) -> None:
    """async_generate_image should call aimage_generation with proper args."""
    raw_response = {"data": "raw"}
    mock_generate = AsyncMock(return_value=raw_response)
    mock_extract = AsyncMock(return_value="normalized-image")

    with (
        patch("hass_nabucasa.llm.aimage_generation", mock_generate),
        patch(
            "hass_nabucasa.llm.LLMHandler._extract_response_image_data", mock_extract
        ),
    ):
        result = await cloud.llm.async_generate_image(prompt="draw a cat")

    assert result == "normalized-image"
    assert mock_generate.await_args is not None
    kwargs = mock_generate.await_args.kwargs
    assert kwargs["prompt"] == "draw a cat"
    assert kwargs["api_key"] == "token"
    assert kwargs["api_base"] == "https://api.example"
    assert kwargs["model"] == "image-model"

    mock_extract.assert_awaited_once_with(raw_response)


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (AuthenticationError("auth", "provider", "model"), LLMAuthenticationError),
        (RateLimitError("ratelimit", "provider", "model"), LLMRateLimitError),
        (ServiceUnavailableError("svc", "provider", "model"), LLMRateLimitError),
        (APIError(500, "api", "provider", "model"), LLMServiceError),
    ],
)
async def test_async_generate_image_maps_errors(
    raised: Exception,
    expected: type[Exception],
    cloud: Cloud,
) -> None:
    """async_generate_image should convert LiteLLM errors to Cloud equivalents."""
    mock_generate = AsyncMock(side_effect=raised)

    with (
        patch("hass_nabucasa.llm.aimage_generation", mock_generate),
        pytest.raises(expected),
    ):
        await cloud.llm.async_generate_image(prompt="draw")


async def test_async_edit_image_single_attachment_payload(cloud: Cloud) -> None:
    """async_edit_image should wrap a single attachment as BytesIO."""
    await cloud.llm.async_ensure_token()

    attachment: LLMImageAttachment = {
        "filename": "first.png",
        "mime_type": "image/png",
        "data": b"payload",
    }
    mock_edit = AsyncMock()
    mock_extract = AsyncMock(return_value="image")

    with (
        patch("hass_nabucasa.llm.aimage_edit", mock_edit),
        patch(
            "hass_nabucasa.llm.LLMHandler._extract_response_image_data", mock_extract
        ),
    ):
        result = await cloud.llm.async_edit_image(
            prompt="prompt",
            attachments=[attachment],
        )

    assert result == "image"
    assert mock_edit.await_args is not None
    kwargs = mock_edit.await_args.kwargs

    assert kwargs["mask"] is None
    image_arg = kwargs["image"]
    assert isinstance(image_arg, io.BytesIO)
    assert image_arg.getvalue() == b"payload"
    assert image_arg.name == "first.png"

    assert kwargs["model"] == "image-model"
    assert kwargs["api_key"] == "token"
    assert kwargs["api_base"] == "https://api.example"

    mock_extract.assert_awaited_once()


async def test_async_edit_image_multiple_attachment_payloads(cloud: Cloud) -> None:
    """async_edit_image should include mask and remaining images."""
    await cloud.llm.async_ensure_token()

    attachments: list[LLMImageAttachment] = [
        {
            "filename": "base.png",
            "mime_type": "image/png",
            "data": b"base",
        },
        {
            "filename": "mask.png",
            "mime_type": "image/png",
            "data": b"mask",
        },
        {
            "filename": "extra.png",
            "mime_type": "image/png",
            "data": b"extra",
        },
    ]

    mock_edit = AsyncMock()
    mock_extract = AsyncMock(return_value="image")

    with (
        patch("hass_nabucasa.llm.aimage_edit", mock_edit),
        patch(
            "hass_nabucasa.llm.LLMHandler._extract_response_image_data", mock_extract
        ),
    ):
        result = await cloud.llm.async_edit_image(
            prompt="prompt",
            attachments=attachments,
        )

    assert result == "image"
    assert mock_edit.await_args is not None
    kwargs = mock_edit.await_args.kwargs

    mask_arg = kwargs["mask"]
    assert isinstance(mask_arg, io.BytesIO)
    assert mask_arg.getvalue() == b"mask"
    assert mask_arg.name == "mask.png"

    image_arg = kwargs["image"]
    assert isinstance(image_arg, list)
    assert [part.getvalue() for part in image_arg] == [b"base", b"extra"]
    assert [part.name for part in image_arg] == ["base.png", "extra.png"]

    assert kwargs["model"] == "image-model"
    assert kwargs["api_key"] == "token"
    assert kwargs["api_base"] == "https://api.example"

    mock_extract.assert_awaited_once()


async def test_async_process_conversation_forwards_arguments(
    cloud: Cloud,
) -> None:
    """async_process_conversation should forward params and return response."""
    response = SimpleNamespace(ok=True)
    mock_aresponses = AsyncMock(return_value=response)

    with patch("hass_nabucasa.llm.aresponses", mock_aresponses):
        result = await cloud.llm.async_process_conversation(
            messages=[{"role": "user", "content": "hello"}],
            conversation_id="conv-id",
            response_format={"type": "json_object"},
            stream=False,
            tools=cast(
                "list[ToolParam]",
                [{"type": "function", "function": {"name": "do_something"}}],
            ),
            tool_choice=cast(
                "ToolChoice", {"type": "function", "function": {"name": "do_something"}}
            ),
        )

    assert result is response
    assert mock_aresponses.await_args is not None
    kwargs = mock_aresponses.await_args.kwargs

    assert kwargs["model"] == "conv-model"
    assert kwargs["input"] == [{"role": "user", "content": "hello"}]
    assert kwargs["api_key"] == "token"
    assert kwargs["api_base"] == "https://api.example"
    assert kwargs["user"] == "conv-id"
    assert kwargs["stream"] is False
    assert kwargs["text_format"] == {"type": "json_object"}
    assert kwargs["tools"] == [
        {"type": "function", "function": {"name": "do_something"}}
    ]
    assert kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "do_something"},
    }


async def test_async_process_conversation_streams_when_requested(
    cloud: Cloud,
) -> None:
    """async_process_conversation should return LiteLLM stream when stream=True."""
    mock_aresponses = AsyncMock()

    with patch("hass_nabucasa.llm.aresponses", mock_aresponses):
        result = await cloud.llm.async_process_conversation(
            messages=[],
            conversation_id="conv-stream",
            stream=True,
        )

    assert result is mock_aresponses.return_value
    assert mock_aresponses.await_args is not None
    assert mock_aresponses.await_args.kwargs["stream"] is True
    # Still should use the conversation model
    assert mock_aresponses.await_args.kwargs["model"] == "conv-model"


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (AuthenticationError("auth", "provider", "model"), LLMAuthenticationError),
        (RateLimitError("ratelimit", "provider", "model"), LLMRateLimitError),
        (ServiceUnavailableError("svc", "provider", "model"), LLMRateLimitError),
        (APIError(500, "api", "provider", "model"), LLMServiceError),
    ],
)
async def test_async_process_conversation_maps_errors(
    raised: Exception,
    expected: type[Exception],
    cloud: Cloud,
) -> None:
    """async_process_conversation should convert LiteLLM errors to Cloud equivalents."""
    mock_aresponses = AsyncMock(side_effect=raised)

    with (
        patch("hass_nabucasa.llm.aresponses", mock_aresponses),
        pytest.raises(expected),
    ):
        await cloud.llm.async_process_conversation(
            messages=[],
            conversation_id="conv",
        )
