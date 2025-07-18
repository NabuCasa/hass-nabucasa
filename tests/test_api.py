"""Test the base API module."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import Mock

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


async def test_exception_handler_preserves_response_attribute() -> None:
    """Test that exception handler preserves response attribute."""
    response_mock = Mock()
    original_exception = CloudApiError("Original error", response=response_mock)

    @api_exception_handler(CustomException)
    async def mock_func() -> None:
        raise original_exception

    with pytest.raises(CustomException) as exc_info:
        await mock_func()

    assert exc_info.value.response is response_mock


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


async def test_pre_request_log_handler_debug_enabled(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test pre-request log handler when DEBUG logging is enabled."""
    test_api = AwesomeApiClass(auth_cloud_mock)

    aioclient_mock.get(
        "https://example.com/test",
        json={"result": "success"},
        status=200,
    )

    with caplog.at_level(logging.DEBUG, logger="hass_nabucasa.api"):
        await test_api._call_cloud_api(
            path="/test",
            method="GET",
            skip_token_check=True,
        )

    assert "Sending GET request to example.com/test" in caplog.text


async def test_pre_request_log_handler_debug_disabled(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test pre-request log handler when DEBUG logging is disabled."""
    test_api = AwesomeApiClass(auth_cloud_mock)

    aioclient_mock.get(
        "https://example.com/test",
        json={"result": "success"},
        status=200,
    )

    with caplog.at_level(logging.INFO, logger="hass_nabucasa.api"):
        await test_api._call_cloud_api(
            path="/test",
            method="GET",
            skip_token_check=True,
        )

    assert "Sending GET request to example.com/test" not in caplog.text


async def test_pre_request_log_handler_with_external_hostname(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test pre-request log handler with external hostname (should not show path)."""
    test_api = AwesomeApiClass(auth_cloud_mock)

    aioclient_mock.get(
        "https://external.com/test",
        json={"result": "success"},
        status=200,
    )

    with caplog.at_level(logging.DEBUG, logger="hass_nabucasa.api"):
        await test_api._call_raw_api(
            method="GET",
            url="https://external.com/test",
            client_timeout=Mock(),
            headers={},
        )

    assert "Sending GET request to external.com" in caplog.text
    assert "Sending GET request to external.com/test" not in caplog.text


async def test_exception_response_attribute_on_parse_error(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
) -> None:
    """Test that response attribute is set when API response parsing fails."""
    test_api = AwesomeApiClass(auth_cloud_mock)

    aioclient_mock.get(
        "https://example.com/test",
        text="",
        status=200,
    )

    with pytest.raises(CloudApiError) as exc_info:
        await test_api._call_cloud_api(
            path="/test",
            method="GET",
            skip_token_check=True,
        )

    assert exc_info.value.response is not None
    assert exc_info.value.response.status == 200


async def test_exception_response_attribute_on_http_error(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
) -> None:
    """Test that response attribute is set when HTTP error occurs."""
    test_api = AwesomeApiClass(auth_cloud_mock)

    aioclient_mock.get(
        "https://example.com/test",
        json={"error": "not found"},
        status=404,
    )

    with pytest.raises(CloudApiError) as exc_info:
        await test_api._call_cloud_api(
            path="/test",
            method="GET",
            skip_token_check=True,
        )

    assert exc_info.value.response is not None
    assert exc_info.value.response.status == 404
