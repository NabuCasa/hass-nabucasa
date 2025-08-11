"""Tests for Google Actions functionality in GoogleReportState."""

import re
from typing import Any

from aiohttp import ClientError
import pytest

from hass_nabucasa import Cloud
from hass_nabucasa.google_report_state import GoogleReportState, GoogleReportStateError
from tests.utils.aiohttp import AiohttpClientMocker

API_HOSTNAME = "example.com"


@pytest.fixture(autouse=True)
def set_hostname(auth_cloud_mock: Cloud):
    """Set API hostname for the mock cloud service."""
    auth_cloud_mock.remotestate_server = API_HOSTNAME


@pytest.mark.parametrize(
    "exception,postmockargs,log_msg,exception_msg",
    [
        [
            GoogleReportStateError,
            {"exc": TimeoutError()},
            "",
            "Timeout reached while calling API",
        ],
        [
            GoogleReportStateError,
            {"exc": ClientError("boom!")},
            "",
            "Failed to fetch: boom!",
        ],
        [
            GoogleReportStateError,
            {"exc": Exception("boom!")},
            "",
            "Unexpected error while calling API: boom!",
        ],
    ],
)
async def test_problems_requesting_sync(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    postmockargs: dict[str, Any],
    log_msg: str,
    exception_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test problems requesting Google Actions sync."""
    google_report_state = GoogleReportState(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/request_sync",
        **postmockargs,
    )

    with pytest.raises(exception, match=re.escape(exception_msg)):
        await google_report_state.request_sync()

    if log_msg:
        assert log_msg in caplog.text


@pytest.mark.parametrize(
    "status,text",
    [
        [500, "Internal Server Error"],
        [429, "Too fast"],
    ],
)
async def test_request_sync_error_status(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    status: int,
    text: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test Google Actions sync request with error status codes."""
    google_report_state = GoogleReportState(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/request_sync",
        status=status,
        text=text,
    )

    response = await google_report_state.request_sync()

    assert response.status == status
    assert f"Response for post from example.com/request_sync ({status})" in caplog.text


async def test_request_sync_success(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test successful Google Actions sync request."""
    google_report_state = GoogleReportState(auth_cloud_mock)
    aioclient_mock.post(
        f"https://{API_HOSTNAME}/request_sync",
        status=200,
    )

    response = await google_report_state.request_sync()

    assert response.status == 200
    assert "Response for post from example.com/request_sync (200)" in caplog.text
