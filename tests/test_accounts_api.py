"""Tests for Instance API."""

import re
from typing import Any

from aiohttp import ClientError
import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa import AccountsApiError, Cloud
from tests.common import extract_log_messages
from tests.utils.aiohttp import AiohttpClientMocker


@pytest.mark.parametrize(
    "exception,mockargs,exception_msg",
    [
        [
            AccountsApiError,
            {"status": 500, "text": "Internal Server Error"},
            "Failed to fetch: (500) ",
        ],
        [
            AccountsApiError,
            {"status": 429, "text": "Too fast"},
            "Failed to fetch: (429) ",
        ],
        [
            AccountsApiError,
            {"exc": TimeoutError()},
            "Timeout reached while calling API",
        ],
        [
            AccountsApiError,
            {"exc": ClientError("boom!")},
            "Failed to fetch: boom!",
        ],
        [
            AccountsApiError,
            {"exc": Exception("boom!")},
            "Unexpected error while calling API: boom!",
        ],
    ],
    ids=["500-error", "429-error", "timeout", "client-error", "unexpected-error"],
)
async def test_resolve_dns_cname_endpoint_problems(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    mockargs: dict[str, Any],
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test problems with resolve_dns_cname endpoint."""
    aioclient_mock.post(
        f"https://{cloud.accounts_server}/instance/resolve_dns_cname",
        **mockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await cloud.accounts.instance_resolve_dns_cname(hostname="example.com")

    assert extract_log_messages(caplog) == snapshot


async def test_resolve_dns_cname_endpoint_success(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test successful resolve_dns_cname endpoint."""
    expected_result = ["alias1.example.com", "alias2.example.com"]

    aioclient_mock.post(
        f"https://{cloud.accounts_server}/instance/resolve_dns_cname",
        json=expected_result,
    )

    result = await cloud.accounts.instance_resolve_dns_cname(hostname="example.com")

    assert result == expected_result
    assert extract_log_messages(caplog) == snapshot
