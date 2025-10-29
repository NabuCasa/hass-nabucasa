"""Test the base API module."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
import voluptuous as vol

from hass_nabucasa.api import (
    ALLOW_EMPTY_RESPONSE,
    ApiBase,
    CloudApiError,
    CloudApiInvalidResponseError,
    CloudApiNonRetryableError,
    CloudApiRawResponse,
    api_exception_handler,
)

if TYPE_CHECKING:
    from hass_nabucasa import Cloud
    from tests.utils.aiohttp import AiohttpClientMocker


class CustomException(CloudApiError):
    """Custom exception for testing."""


@pytest.fixture(autouse=True)
def add_test_api_action_to_service_discovery():
    """Add test_api_action for this module's tests."""
    with (
        patch(
            "hass_nabucasa.service_discovery.VALID_ACTION_NAMES",
            frozenset(["test_api_action"]),
        ),
        patch(
            "hass_nabucasa.service_discovery.ServiceDiscovery._get_service_action_url",
            return_value="https://example.com/test/{param}/action",
        ),
    ):
        yield


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
    cloud: Cloud,
    method: str,
) -> None:
    """Test empty response handling for methods that allow empty responses."""
    test_api = AwesomeApiClass(cloud)

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
    cloud: Cloud,
    method: str,
) -> None:
    """Test empty response handling for methods that disallow empty responses."""
    test_api = AwesomeApiClass(cloud)

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
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test pre-request log handler when DEBUG logging is enabled."""
    test_api = AwesomeApiClass(cloud)

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
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test pre-request log handler when DEBUG logging is disabled."""
    test_api = AwesomeApiClass(cloud)

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
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test pre-request log handler with external hostname (should not show path)."""
    test_api = AwesomeApiClass(cloud)

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
    cloud: Cloud,
) -> None:
    """Test raw_response parameter returns CloudApiRawResponse."""
    test_api = AwesomeApiClass(cloud)

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
    cloud: Cloud,
) -> None:
    """Test raw_response parameter with error status codes."""
    test_api = AwesomeApiClass(cloud)

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
    cloud: Cloud,
) -> None:
    """Test raw_response parameter with empty response data."""
    test_api = AwesomeApiClass(cloud)

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
    cloud: Cloud,
) -> None:
    """Test raw_response parameter with JSON response data."""
    test_api = AwesomeApiClass(cloud)

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


@pytest.mark.parametrize(
    "params,query_string,params_in_log",
    [
        [{"param": "value"}, "param=value", "param=***"],
        [
            {"param": "value", "param2": "value2"},
            "param=value&param2=value2",
            "param=***&param2=***",
        ],
        [{"param": "True"}, "param=True", "param=True"],
        [{"param": "false"}, "param=false", "param=false"],
        [
            {"param": "value", "param2": "true", "param3": "value3", "param4": "false"},
            "param=value&param2=true&param3=value3&param4=false",
            "param=***&param2=true&param3=***&param4=false",
        ],
    ],
)
async def test_raw_response_with_params(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    params: dict,
    query_string: str,
    params_in_log: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test raw_response parameter with JSON response data."""
    test_api = AwesomeApiClass(cloud)

    test_data = {"message": "Hello", "count": 42}
    aioclient_mock.get(
        f"https://example.com/test?{query_string}",
        json=test_data,
        status=200,
    )

    result = await test_api._call_cloud_api(
        path="/test",
        method="GET",
        raw_response=True,
        params=params,
    )

    assert isinstance(result, CloudApiRawResponse)
    assert result.data == test_data
    assert result.response.status == 200
    assert (
        f"Response for get from example.com/test?{params_in_log} (200)" in caplog.text
    )


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


async def test_call_cloud_api_with_action_parameter(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test _call_cloud_api with action parameter."""
    test_api = AwesomeApiClass(cloud)

    aioclient_mock.get(
        "https://example.com/test/value/action",
        json={"result": "success"},
        status=200,
    )

    result = await test_api._call_cloud_api(
        action="test_api_action",
        action_values={"param": "value"},
        method="GET",
    )

    assert result == {"result": "success"}


async def test_call_cloud_api_with_path_parameter(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test _call_cloud_api with path parameter."""
    test_api = AwesomeApiClass(cloud)

    aioclient_mock.get(
        "https://example.com/test",
        json={"result": "success"},
        status=200,
    )

    result = await test_api._call_cloud_api(
        path="/test",
        method="GET",
    )

    assert result == {"result": "success"}


async def test_call_cloud_api_action_takes_precedence_over_path(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test that action parameter takes precedence over path parameter."""
    test_api = AwesomeApiClass(cloud)

    aioclient_mock.get(
        "https://example.com/test/value/action",
        json={"result": "from action"},
        status=200,
    )

    result = await test_api._call_cloud_api(
        action="test_api_action",
        action_values={"param": "value"},
        path="/path-endpoint",
        method="GET",
    )

    assert result == {"result": "from action"}


async def test_call_cloud_api_requires_action_or_path(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test that _call_cloud_api requires either action or path parameter."""
    test_api = AwesomeApiClass(cloud)

    with pytest.raises(
        CloudApiError, match="Either 'action' or 'path' parameter must be provided"
    ):
        await test_api._call_cloud_api(method="GET")


async def test_call_cloud_api_with_schema_validation_success(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test _call_cloud_api with schema validation (valid data)."""
    test_api = AwesomeApiClass(cloud)

    test_schema = vol.Schema(
        {
            vol.Required("name"): str,
            vol.Required("count"): int,
        }
    )

    aioclient_mock.get(
        "https://example.com/test",
        json={"name": "test", "count": 42},
        status=200,
    )

    result = await test_api._call_cloud_api(
        path="/test",
        method="GET",
        schema=test_schema,
    )

    assert result == {"name": "test", "count": 42}


async def test_call_cloud_api_with_schema_validation_failure(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test _call_cloud_api with schema validation (invalid data)."""
    test_api = AwesomeApiClass(cloud)

    test_schema = vol.Schema(
        {
            vol.Required("name"): str,
            vol.Required("count"): int,
        }
    )

    aioclient_mock.get(
        "https://example.com/test",
        json={"name": "test", "count": "not-a-number"},
        status=200,
    )

    with pytest.raises(CloudApiInvalidResponseError, match="Invalid response"):
        await test_api._call_cloud_api(
            path="/test",
            method="GET",
            schema=test_schema,
        )


async def test_call_cloud_api_with_schema_validation_missing_field(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test _call_cloud_api with schema validation (missing required field)."""
    test_api = AwesomeApiClass(cloud)

    test_schema = vol.Schema(
        {
            vol.Required("name"): str,
            vol.Required("count"): int,
        }
    )

    aioclient_mock.get(
        "https://example.com/test",
        json={"name": "test"},
        status=200,
    )

    with pytest.raises(CloudApiInvalidResponseError, match="Invalid response"):
        await test_api._call_cloud_api(
            path="/test",
            method="GET",
            schema=test_schema,
        )


async def test_call_cloud_api_schema_validation_with_coercion(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test _call_cloud_api with schema that coerces data types."""
    test_api = AwesomeApiClass(cloud)

    test_schema = vol.Schema(
        {
            vol.Required("value"): vol.Coerce(int),
        }
    )

    aioclient_mock.get(
        "https://example.com/test",
        json={"value": "123"},
        status=200,
    )

    result = await test_api._call_cloud_api(
        path="/test",
        method="GET",
        schema=test_schema,
    )

    assert result == {"value": 123}


async def test_action_url_via_service_discovery(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test action_url method via service discovery."""
    url = cloud.service_discovery.action_url("test_api_action", param="value")

    assert isinstance(url, str)
    assert url == "https://example.com/test/value/action"


async def test_call_cloud_api_with_action_values(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test _call_cloud_api with action_values for format parameters."""
    test_api = AwesomeApiClass(cloud)

    # Use a context manager to override the patched method for this test
    with patch(
        "hass_nabucasa.service_discovery.ServiceDiscovery._get_service_action_url",
        return_value="https://example.com/test/{param}/details",
    ):
        aioclient_mock.get(
            "https://example.com/test/value/details",
            json={"result": "success"},
            status=200,
        )

        result = await test_api._call_cloud_api(
            action="test_api_action",
            action_values={"param": "value"},
            method="GET",
        )

        assert result == {"result": "success"}


async def test_hostname_property_default(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test that hostname property defaults to None."""
    test_api = ApiBase(cloud)

    assert test_api.hostname is None


async def test_hostname_property_override(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
) -> None:
    """Test that hostname property can be overridden."""
    test_api = AwesomeApiClass(cloud)

    assert test_api.hostname == "example.com"
