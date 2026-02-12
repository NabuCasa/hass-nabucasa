"""Test cloud cloudhooks."""

from unittest.mock import AsyncMock, patch

import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa import Cloud
from hass_nabucasa.const import STATE_CONNECTED
from hass_nabucasa.events.types import (
    CloudEventType,
    CloudhookCreatedEvent,
    CloudhookDeletedEvent,
)
from tests.common import extract_log_messages
from tests.utils.aiohttp import AiohttpClientMocker


async def test_enable(
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test enabling cloudhooks."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/instance/webhook",
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

    cloud.iot.state = STATE_CONNECTED
    with patch(
        "hass_nabucasa.iot.CloudIoT.async_send_message", new_callable=AsyncMock
    ) as mock_send:
        result = await cloud.cloudhooks.async_create("mock-webhook-id", False)

    assert result == hook
    assert cloud.client.cloudhooks == {"mock-webhook-id": hook}

    assert len(mock_send.mock_calls) == 1
    assert mock_send.mock_calls[0][1][0] == "webhook-register"
    assert mock_send.mock_calls[0][1][1] == {"cloudhook_ids": ["mock-cloud-id"]}
    assert extract_log_messages(caplog) == snapshot


async def test_delete(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test deleting a cloudhook."""
    cloud.client._cloudhooks = {
        "mock-webhook-id": {
            "webhook_id": "mock-webhook-id",
            "cloudhook_id": "mock-cloud-id",
            "cloudhook_url": "https://hooks.nabu.casa/ZXCZCXZ",
        },
    }

    cloud.iot.state = STATE_CONNECTED
    with patch(
        "hass_nabucasa.iot.CloudIoT.async_send_message", new_callable=AsyncMock
    ) as mock_send:
        await cloud.cloudhooks.async_delete("mock-webhook-id")

    assert cloud.client.cloudhooks == {}

    assert len(mock_send.mock_calls) == 1
    assert mock_send.mock_calls[0][1][0] == "webhook-register"
    assert mock_send.mock_calls[0][1][1] == {"cloudhook_ids": []}
    assert extract_log_messages(caplog) == snapshot


async def test_create_publishes_cloudhook_created_event(
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
):
    """Test that async_create publishes a CloudhookCreatedEvent."""
    aioclient_mock.get(
        f"https://{cloud.api_server}/instance/webhook",
        json={
            "cloudhook_id": "mock-cloud-id",
            "url": "https://hooks.nabu.casa/ZXCZCXZ",
        },
    )

    subscriber = AsyncMock()
    cloud.events.subscribe(
        event_type=CloudEventType.CLOUDHOOK_CREATED, handler=subscriber
    )

    cloud.iot.state = STATE_CONNECTED
    with patch("hass_nabucasa.iot.CloudIoT.async_send_message", new_callable=AsyncMock):
        await cloud.cloudhooks.async_create("mock-webhook-id", False)

    assert len(subscriber.call_args_list) == 1
    event = subscriber.call_args_list[0][0][0]
    assert isinstance(event, CloudhookCreatedEvent)
    assert event.type == CloudEventType.CLOUDHOOK_CREATED
    assert event.cloudhook == {
        "webhook_id": "mock-webhook-id",
        "cloudhook_id": "mock-cloud-id",
        "cloudhook_url": "https://hooks.nabu.casa/ZXCZCXZ",
        "managed": False,
    }
    assert event.timestamp is not None


async def test_delete_publishes_cloudhook_deleted_event(
    cloud: Cloud,
):
    """Test that async_delete publishes a CloudhookDeletedEvent."""
    cloud.client._cloudhooks = {
        "mock-webhook-id": {
            "webhook_id": "mock-webhook-id",
            "cloudhook_id": "mock-cloud-id",
            "cloudhook_url": "https://hooks.nabu.casa/ZXCZCXZ",
            "managed": True,
        },
    }

    subscriber = AsyncMock()
    cloud.events.subscribe(
        event_type=CloudEventType.CLOUDHOOK_DELETED, handler=subscriber
    )

    cloud.iot.state = STATE_CONNECTED
    with patch("hass_nabucasa.iot.CloudIoT.async_send_message", new_callable=AsyncMock):
        await cloud.cloudhooks.async_delete("mock-webhook-id")

    assert len(subscriber.call_args_list) == 1
    event = subscriber.call_args_list[0][0][0]
    assert isinstance(event, CloudhookDeletedEvent)
    assert event.type == CloudEventType.CLOUDHOOK_DELETED
    assert event.cloudhook == {
        "webhook_id": "mock-webhook-id",
        "cloudhook_id": "mock-cloud-id",
        "cloudhook_url": "https://hooks.nabu.casa/ZXCZCXZ",
        "managed": True,
    }
    assert event.timestamp is not None


async def test_create_without_connected(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test we raise ValueError if not connected."""
    assert cloud.iot.state != STATE_CONNECTED
    with pytest.raises(ValueError, match="Cloud is not connected"):
        await cloud.cloudhooks.async_create("mock-webhook-id", True)

    assert cloud.client.cloudhooks == {}
    assert extract_log_messages(caplog) == snapshot
