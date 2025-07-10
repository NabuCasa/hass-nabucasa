"""Tests for Instance API."""

from typing import Any

from aiohttp import ClientError
import pytest

from hass_nabucasa import Cloud
from hass_nabucasa.instance_api import (
    InstanceApi,
    InstanceApiError,
)
from tests.utils.aiohttp import AiohttpClientMocker

API_HOSTNAME = "example.com"


@pytest.fixture(autouse=True)
def set_hostname(auth_cloud_mock: Cloud):
    """Set API hostname for the mock cloud service."""
    auth_cloud_mock.servicehandlers_server = API_HOSTNAME


@pytest.mark.parametrize(
    "method_name,http_method,path,params",
    [
        (
            "connection",
            "GET",
            "/instance/connection",
            {},
        ),
        (
            "resolve_dns_cname",
            "POST",
            "/instance/resolve_dns_cname",
            {"hostname": "example.com"},
        ),
        (
            "cleanup_dns_challenge_record",
            "POST",
            "/instance/dns_challenge_cleanup",
            {"value": "challenge-value"},
        ),
        (
            "create_dns_challenge_record",
            "POST",
            "/instance/dns_challenge_txt",
            {"value": "challenge-value"},
        ),
    ],
)
@pytest.mark.parametrize(
    "exception,mockargs,log_msg_template,exception_msg",
    [
        [
            InstanceApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for {method} from example.com{path} (500)",
            "Failed to parse API response",
        ],
        [
            InstanceApiError,
            {"status": 429, "text": "Too fast"},
            "Response for {method} from example.com{path} (429)",
            "Failed to parse API response",
        ],
        [
            InstanceApiError,
            {"exc": TimeoutError()},
            "",
            "Timeout reached while calling API",
        ],
        [
            InstanceApiError,
            {"exc": ClientError("boom!")},
            "",
            "Failed to fetch: boom!",
        ],
        [
            InstanceApiError,
            {"exc": Exception("boom!")},
            "",
            "Unexpected error while calling API: boom!",
        ],
    ],
)
async def test_instance_api_methods_problems(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    method_name: str,
    http_method: str,
    path: str,
    params: dict[str, Any],
    exception: Exception,
    mockargs: dict[str, Any],
    log_msg_template: str,
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems with instance API methods."""
    instance_api = InstanceApi(auth_cloud_mock)

    if http_method == "GET":
        aioclient_mock.get(
            f"https://{API_HOSTNAME}{path}",
            **mockargs,
        )
    else:
        aioclient_mock.post(
            f"https://{API_HOSTNAME}{path}",
            **mockargs,
        )

    method = getattr(instance_api, method_name)
    with pytest.raises(exception, match=exception_msg):
        await method(**params)

    log_msg = (
        log_msg_template.format(method=http_method.lower(), path=path)
        if log_msg_template
        else ""
    )
    assert log_msg in caplog.text


@pytest.mark.parametrize(
    "method_name,http_method,path,params,expected_result",
    [
        (
            "connection",
            "GET",
            "/instance/connection",
            {},
            {"connected": True, "details": {}},
        ),
        (
            "resolve_dns_cname",
            "POST",
            "/instance/resolve_dns_cname",
            {"hostname": "example.com"},
            ["alias1.example.com", "alias2.example.com"],
        ),
        (
            "cleanup_dns_challenge_record",
            "POST",
            "/instance/dns_challenge_cleanup",
            {"value": "challenge-value"},
            None,
        ),
        (
            "create_dns_challenge_record",
            "POST",
            "/instance/dns_challenge_txt",
            {"value": "challenge-value"},
            None,
        ),
    ],
)
async def test_instance_api_methods_success(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    method_name: str,
    http_method: str,
    path: str,
    params: dict[str, Any],
    expected_result: Any,
    caplog: pytest.LogCaptureFixture,
):
    """Test successful instance API methods."""
    instance_api = InstanceApi(auth_cloud_mock)

    if http_method == "GET":
        aioclient_mock.get(
            f"https://{API_HOSTNAME}{path}",
            json=expected_result,
        )
    elif expected_result is not None:
        aioclient_mock.post(
            f"https://{API_HOSTNAME}{path}",
            json=expected_result,
        )
    else:
        aioclient_mock.post(
            f"https://{API_HOSTNAME}{path}",
            json={},
        )

    method = getattr(instance_api, method_name)
    result = await method(**params)

    assert result == expected_result
    assert (
        f"Response for {http_method.lower()} from example.com{path} (200)"
        in caplog.text
    )
