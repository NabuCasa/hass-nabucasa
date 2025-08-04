"""Tests for Instance API."""

import re
from typing import Any

from aiohttp import ClientError
import pytest

from hass_nabucasa import AccountsApi, AccountsApiError, Cloud
from tests.utils.aiohttp import AiohttpClientMocker

API_HOSTNAME = "example.com"


@pytest.fixture(autouse=True)
def set_hostname(auth_cloud_mock: Cloud):
    """Set API hostname for the mock cloud service."""
    auth_cloud_mock.accounts_server = API_HOSTNAME


@pytest.mark.parametrize(
    "exception,mockargs,log_msg_template,exception_msg",
    [
        [
            AccountsApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for post from example.com/instance/resolve_dns_cname (500)",
            "Failed to fetch: (500) ",
        ],
        [
            AccountsApiError,
            {"status": 429, "text": "Too fast"},
            "Response for post from example.com/instance/resolve_dns_cname (429)",
            "Failed to fetch: (429) ",
        ],
        [
            AccountsApiError,
            {"exc": TimeoutError()},
            "",
            "Timeout reached while calling API",
        ],
        [
            AccountsApiError,
            {"exc": ClientError("boom!")},
            "",
            "Failed to fetch: boom!",
        ],
        [
            AccountsApiError,
            {"exc": Exception("boom!")},
            "",
            "Unexpected error while calling API: boom!",
        ],
    ],
    ids=["500-error", "429-error", "timeout", "client-error", "unexpected-error"],
)
async def test_resolve_dns_cname_endpoint_problems(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    mockargs: dict[str, Any],
    log_msg_template: str,
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems with resolve_dns_cname endpoint."""
    accouunts_api = AccountsApi(auth_cloud_mock)

    aioclient_mock.post(
        f"https://{API_HOSTNAME}/instance/resolve_dns_cname",
        **mockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await accouunts_api.instance_resolve_dns_cname(hostname="example.com")

    if log_msg_template:
        assert log_msg_template in caplog.text


async def test_resolve_dns_cname_endpoint_success(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test successful resolve_dns_cname endpoint."""
    accounts_api = AccountsApi(auth_cloud_mock)
    expected_result = ["alias1.example.com", "alias2.example.com"]

    aioclient_mock.post(
        f"https://{API_HOSTNAME}/instance/resolve_dns_cname",
        json=expected_result,
    )

    result = await accounts_api.instance_resolve_dns_cname(hostname="example.com")

    assert result == expected_result
    assert (
        "Response for post from example.com/instance/resolve_dns_cname (200)"
        in caplog.text
    )
