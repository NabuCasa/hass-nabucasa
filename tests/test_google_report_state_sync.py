"""Tests for Google Actions functionality in GoogleReportState."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError
import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa.google_report_state import GoogleReportState, GoogleReportStateError
from tests.common import extract_log_messages

if TYPE_CHECKING:
    from hass_nabucasa import Cloud
    from tests.utils.aiohttp import AiohttpClientMocker


@pytest.mark.parametrize(
    "exception,postmockargs,exception_msg",
    [
        [
            GoogleReportStateError,
            {"exc": TimeoutError()},
            "Timeout reached while calling API",
        ],
        [
            GoogleReportStateError,
            {"exc": ClientError("boom!")},
            "Failed to fetch: boom!",
        ],
        [
            GoogleReportStateError,
            {"exc": Exception("boom!")},
            "Unexpected error while calling API: boom!",
        ],
    ],
    ids=["timeout", "client-error", "unexpected-error"],
)
async def test_problems_requesting_sync(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    postmockargs: dict[str, Any],
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test problems requesting Google Actions sync."""
    google_report_state = GoogleReportState(cloud)
    aioclient_mock.post(
        f"https://{cloud.remotestate_server}/request_sync",
        **postmockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await google_report_state.request_sync()

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.parametrize(
    "status,text",
    [
        [500, "Internal Server Error"],
        [429, "Too fast"],
    ],
    ids=["500-error", "429-error"],
)
async def test_request_sync_error_status(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    status: int,
    text: str,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test Google Actions sync request with error status codes."""
    google_report_state = GoogleReportState(cloud)
    aioclient_mock.post(
        f"https://{cloud.remotestate_server}/request_sync",
        status=status,
        text=text,
    )

    response = await google_report_state.request_sync()

    assert response.status == status
    assert extract_log_messages(caplog) == snapshot


async def test_request_sync_success(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test successful Google Actions sync request."""
    google_report_state = GoogleReportState(cloud)
    aioclient_mock.post(
        f"https://{cloud.remotestate_server}/request_sync",
        status=200,
    )

    response = await google_report_state.request_sync()

    assert response.status == 200
    assert extract_log_messages(caplog) == snapshot
