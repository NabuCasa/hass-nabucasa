"""Test the base API module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from hass_nabucasa.api import (
    ALLOW_EMPTY_RESPONSE,
    ApiBase,
    CloudApiError,
    CloudApiNonRetryableError,
    api_exception_handler,
)

if TYPE_CHECKING:
    from hass_nabucasa import Cloud
    from tests.utils.aiohttp import AiohttpClientMocker


class CustomException(CloudApiError):
    """Custom exception for testing."""


@pytest.mark.parametrize(
    "exception,expected",
    [
        (CloudApiError("Oh no!"), CloudApiError),
        (CloudApiNonRetryableError("Oh no!", code="616"), CloudApiNonRetryableError),
        (CustomException("Oh no!"), CustomException),
        (KeyError("stt"), CustomException),
    ],
)
async def test_raising_exception(exception, expected) -> None:
    """Test raising a custom exception."""

    @api_exception_handler(CustomException)
    async def mock_func() -> None:
        raise exception

    with pytest.raises(expected):
        await mock_func()


class AwesomeApiClass(ApiBase):
    """Test API implementation."""

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        return "example.com"


@pytest.mark.parametrize(
    "method",
    ALLOW_EMPTY_RESPONSE,
)
async def test_empty_response_handling_allowed_methods(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    method: str,
) -> None:
    """Test empty response handling for methods that allow empty responses."""
    test_api = AwesomeApiClass(auth_cloud_mock)

    aioclient_mock.request(
        method.lower(),
        "https://example.com/test",
        text="",
        status=200,
    )

    result = await test_api._call_cloud_api(
        path="/test",
        method=method,
        skip_token_check=True,
    )
    assert result is None


@pytest.mark.parametrize(
    "method",
    ["GET", "PUT", "PATCH", "OPTIONS"],
)
async def test_empty_response_handling_disallowed_methods(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    method: str,
) -> None:
    """Test empty response handling for methods that disallow empty responses."""
    test_api = AwesomeApiClass(auth_cloud_mock)

    aioclient_mock.request(
        method.lower(),
        "https://example.com/test",
        text="",
        status=200,
    )

    with pytest.raises(CloudApiError, match="Failed to parse API response"):
        await test_api._call_cloud_api(
            path="/test",
            method=method,
            skip_token_check=True,
        )
