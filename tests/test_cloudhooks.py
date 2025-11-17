"""Test cloud cloudhooks."""

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa import Cloud
from tests.common import extract_log_messages
from tests.utils.aiohttp import AiohttpClientMocker


@pytest.fixture
def async_send_message_mock() -> Generator[Any, Any, AsyncMock]:
    """Mock async_send_message."""
    with (
        patch(
            "hass_nabucasa.Cloud.is_connected",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "hass_nabucasa.CloudIoT.connected",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch("hass_nabucasa.CloudIoT.async_send_message") as mock_send_message,
    ):
        yield mock_send_message


async def test_enable(
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
    async_send_message_mock: AsyncMock,
):
    """Test enabling cloudhooks."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/instance/webhook",
        json={
            "cloudhook_id": "mock-cloud-id",
            "url": "https://hooks.nabu.casa/ZXCZCXZ",
        },
    )

    hook = {
        "webhook_id": "mock-webhook-id",
        "cloudhook_id": "mock-cloud-id",
        "cloudhook_url": "https://hooks.nabu.casa/ZXCZCXZ",
        "managed": False,
    }
    assert cloud.is_connected
    assert hook == await cloud.cloudhooks.async_create("mock-webhook-id", False)

    assert cloud.client.cloudhooks == {"mock-webhook-id": hook}

    assert len(async_send_message_mock.mock_calls) == 1
    assert async_send_message_mock.mock_calls[0][1][0] == "webhook-register"
    assert async_send_message_mock.mock_calls[0][1][1] == {
        "cloudhook_ids": ["mock-cloud-id"]
    }
    assert extract_log_messages(caplog) == snapshot


async def test_disable(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
    async_send_message_mock: AsyncMock,
):
    """Test disabling cloudhooks."""
    cloud.client._cloudhooks = {
        "mock-webhook-id": {
            "webhook_id": "mock-webhook-id",
            "cloudhook_id": "mock-cloud-id",
            "cloudhook_url": "https://hooks.nabu.casa/ZXCZCXZ",
        },
    }

    await cloud.cloudhooks.async_delete("mock-webhook-id")

    assert cloud.client.cloudhooks == {}

    assert len(async_send_message_mock.mock_calls) == 1
    assert async_send_message_mock.mock_calls[0][1][0] == "webhook-register"
    assert async_send_message_mock.mock_calls[0][1][1] == {"cloudhook_ids": []}
    assert extract_log_messages(caplog) == snapshot


async def test_create_without_connected(
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test we raise error when creating a hook if not connected."""
    with (
        patch(
            "hass_nabucasa.Cloud.is_connected",
            new_callable=PropertyMock,
            return_value=False,
        ),
        patch(
            "hass_nabucasa.CloudIoT.connected",
            new_callable=PropertyMock,
            return_value=False,
        ),
        pytest.raises(ValueError, match="Cloud is not connected"),
    ):
        await cloud.cloudhooks.async_create("mock-webhook-id", True)
    assert extract_log_messages(caplog) == snapshot
