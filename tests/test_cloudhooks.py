"""Test cloud cloudhooks."""

from unittest.mock import AsyncMock, Mock

import pytest

from hass_nabucasa import cloudhooks


@pytest.fixture
def mock_cloudhooks(auth_cloud_mock):
    """Mock cloudhooks class."""
    auth_cloud_mock.run_executor = AsyncMock()
    auth_cloud_mock.iot = Mock(async_send_message=AsyncMock())
    auth_cloud_mock.cloudhook_server = "webhook-create.url"
    return cloudhooks.Cloudhooks(auth_cloud_mock)


async def test_enable(mock_cloudhooks, aioclient_mock):
    """Test enabling cloudhooks."""
    aioclient_mock.post(
        "https://webhook-create.url/generate",
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

    assert hook == await mock_cloudhooks.async_create("mock-webhook-id", False)

    assert mock_cloudhooks.cloud.client.cloudhooks == {"mock-webhook-id": hook}

    publish_calls = mock_cloudhooks.cloud.iot.async_send_message.mock_calls
    assert len(publish_calls) == 1
    assert publish_calls[0][1][0] == "webhook-register"
    assert publish_calls[0][1][1] == {"cloudhook_ids": ["mock-cloud-id"]}


async def test_disable(mock_cloudhooks):
    """Test disabling cloudhooks."""
    mock_cloudhooks.cloud.client._cloudhooks = {
        "mock-webhook-id": {
            "webhook_id": "mock-webhook-id",
            "cloudhook_id": "mock-cloud-id",
            "cloudhook_url": "https://hooks.nabu.casa/ZXCZCXZ",
        },
    }

    await mock_cloudhooks.async_delete("mock-webhook-id")

    assert mock_cloudhooks.cloud.client.cloudhooks == {}

    publish_calls = mock_cloudhooks.cloud.iot.async_send_message.mock_calls
    assert len(publish_calls) == 1
    assert publish_calls[0][1][0] == "webhook-register"
    assert publish_calls[0][1][1] == {"cloudhook_ids": []}


async def test_create_without_connected(mock_cloudhooks, aioclient_mock):
    """Test we don't publish a hook if not connected."""
    mock_cloudhooks.cloud.is_connected = False
    # Make sure we fail test when we send a message.
    mock_cloudhooks.cloud.iot.async_send_message.side_effect = ValueError

    aioclient_mock.post(
        "https://webhook-create.url/generate",
        json={
            "cloudhook_id": "mock-cloud-id",
            "url": "https://hooks.nabu.casa/ZXCZCXZ",
        },
    )

    hook = {
        "webhook_id": "mock-webhook-id",
        "cloudhook_id": "mock-cloud-id",
        "cloudhook_url": "https://hooks.nabu.casa/ZXCZCXZ",
        "managed": True,
    }

    assert hook == await mock_cloudhooks.async_create("mock-webhook-id", True)

    assert mock_cloudhooks.cloud.client.cloudhooks == {"mock-webhook-id": hook}

    assert len(mock_cloudhooks.cloud.iot.async_send_message.mock_calls) == 0
