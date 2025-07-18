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
    CloudApiRawResponse,
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


async def test_raw_response_success(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
) -> None:
    """Test raw_response parameter returns CloudApiRawResponse."""
    test_api = AwesomeApiClass(auth_cloud_mock)

    aioclient_mock.get(
        "https://example.com/test",
        json={"result": "success"},
        status=200,
    )

    result = await test_api._call_cloud_api(
        path="/test",
        method="GET",
        raw_response=True,
    )

    assert isinstance(result, CloudApiRawResponse)
    assert result.data == {"result": "success"}
    assert result.response.status == 200


async def test_raw_response_error_handling(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
) -> None:
    """Test raw_response parameter with error status codes."""
    test_api = AwesomeApiClass(auth_cloud_mock)

    aioclient_mock.get(
        "https://example.com/test",
        json={"error": "Not found"},
        status=404,
    )

    result = await test_api._call_cloud_api(
        path="/test",
        method="GET",
        raw_response=True,
    )

    assert isinstance(result, CloudApiRawResponse)
    assert result.data == {"error": "Not found"}
    assert result.response.status == 404


async def test_raw_response_with_empty_data(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
) -> None:
    """Test raw_response parameter with empty response data."""
    test_api = AwesomeApiClass(auth_cloud_mock)

    aioclient_mock.post(
        "https://example.com/test",
        text="",
        status=200,
    )

    result = await test_api._call_cloud_api(
        path="/test",
        method="POST",
        raw_response=True,
    )

    assert isinstance(result, CloudApiRawResponse)
    assert result.data is None
    assert result.response.status == 200


async def test_raw_response_with_json_data(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
) -> None:
    """Test raw_response parameter with JSON response data."""
    test_api = AwesomeApiClass(auth_cloud_mock)

    test_data = {"message": "Hello", "count": 42}
    aioclient_mock.put(
        "https://example.com/test",
        json=test_data,
        status=201,
    )

    result = await test_api._call_cloud_api(
        path="/test",
        method="PUT",
        raw_response=True,
    )

    assert isinstance(result, CloudApiRawResponse)
    assert result.data == test_data
    assert result.response.status == 201


def test_cloud_api_raw_response_dataclass():
    """Test CloudApiRawResponse dataclass structure."""
    mock_response = Mock()
    mock_response.status = 200
    test_data = {"test": "data"}

    raw_response = CloudApiRawResponse(response=mock_response, data=test_data)

    assert raw_response.response == mock_response
    assert raw_response.data == test_data
    assert raw_response.response.status == 200


def test_cloud_api_raw_response_dataclass_default_data():
    """Test CloudApiRawResponse dataclass with default data."""
    mock_response = Mock()
    mock_response.status = 204

    raw_response = CloudApiRawResponse(response=mock_response)

    assert raw_response.response == mock_response
    assert raw_response.data is None
    assert raw_response.response.status == 204
