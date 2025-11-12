"""Tests for event bus."""

from unittest.mock import AsyncMock

import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa import Cloud
from hass_nabucasa.events.bus import EventBusError
from hass_nabucasa.events.types import (
    CloudEventType,
    RelayerConnectedEvent,
    RelayerDisconnectedEvent,
)
from tests.common import extract_log_messages


@pytest.mark.asyncio
async def test_subscribe_and_publish(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test basic subscription and publishing."""
    subscriber = AsyncMock()

    unsubscribe = cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=subscriber
    )

    await cloud.events.publish(event=RelayerConnectedEvent())

    assert len(subscriber.call_args_list) == 1

    unsubscribe()

    assert subscriber.call_args_list == snapshot
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_publish_without_data(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test publishing without extra fields."""
    subscriber = AsyncMock()

    cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED,
        handler=subscriber,
    )

    event = RelayerConnectedEvent()
    await cloud.events.publish(event=event)

    assert len(subscriber.call_args_list) == 1
    assert subscriber.call_args_list[0][0][0].type == CloudEventType.RELAYER_CONNECTED
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_publish_without_subscribers(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test publishing without any subscribers doesn't raise."""
    event = RelayerConnectedEvent()
    await cloud.events.publish(event=event)

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_unsubscribe(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test unsubscribing from events."""
    subscriber = AsyncMock()

    unsubscribe = cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=subscriber
    )

    await cloud.events.publish(event=RelayerConnectedEvent())
    assert len(subscriber.call_args_list) == 1

    unsubscribe()

    await cloud.events.publish(event=RelayerConnectedEvent())
    assert len(subscriber.call_args_list) == 1

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_unsubscribe_multiple_times(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that unsubscribing multiple times doesn't raise."""
    subscriber = AsyncMock()

    unsubscribe = cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=subscriber
    )

    unsubscribe()
    unsubscribe()

    await cloud.events.publish(event=RelayerConnectedEvent())
    assert len(subscriber.call_args_list) == 0

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_error_handling(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that errors in handlers don't stop other handlers."""
    failing_subscriber = AsyncMock(side_effect=ValueError("Test error"))
    working_subscriber = AsyncMock()

    cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=failing_subscriber
    )
    cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=working_subscriber
    )

    await cloud.events.publish(event=RelayerConnectedEvent())

    assert len(failing_subscriber.call_args_list) == 1
    assert len(working_subscriber.call_args_list) == 1
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_multiple_event_types(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test subscribing to different event types."""
    connected_subscriber = AsyncMock()
    disconnected_subscriber = AsyncMock()

    cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=connected_subscriber
    )
    cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_DISCONNECTED, handler=disconnected_subscriber
    )

    await cloud.events.publish(event=RelayerConnectedEvent())
    await cloud.events.publish(event=RelayerDisconnectedEvent())

    assert len(connected_subscriber.call_args_list) == 1
    assert len(disconnected_subscriber.call_args_list) == 1
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_multiple_subscribers(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test multiple subscribers to the same event."""
    subscriber1 = AsyncMock()
    subscriber2 = AsyncMock()
    subscriber3 = AsyncMock()

    cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=subscriber1
    )
    cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=subscriber2
    )
    cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=subscriber3
    )

    await cloud.events.publish(event=RelayerConnectedEvent())

    assert len(subscriber1.call_args_list) == 1
    assert len(subscriber2.call_args_list) == 1
    assert len(subscriber3.call_args_list) == 1
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_event_timestamp(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that events have timestamps."""
    subscriber = AsyncMock()

    cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=subscriber
    )

    await cloud.events.publish(event=RelayerConnectedEvent())

    assert len(subscriber.call_args_list) == 1
    assert subscriber.call_args_list[0][0][0].timestamp is not None
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_subscribe_to_multiple_event_types(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test subscribing to multiple event types with a single handler."""
    subscriber = AsyncMock()

    unsubscribe = cloud.events.subscribe(
        event_type=[
            CloudEventType.RELAYER_CONNECTED,
            CloudEventType.RELAYER_DISCONNECTED,
        ],
        handler=subscriber,
    )

    await cloud.events.publish(event=RelayerConnectedEvent())
    await cloud.events.publish(event=RelayerDisconnectedEvent())

    assert len(subscriber.call_args_list) == 2
    assert subscriber.call_args_list[0][0][0].type == CloudEventType.RELAYER_CONNECTED
    assert (
        subscriber.call_args_list[1][0][0].type == CloudEventType.RELAYER_DISCONNECTED
    )

    unsubscribe()

    await cloud.events.publish(event=RelayerConnectedEvent())
    assert len(subscriber.call_args_list) == 2

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_subscribe_to_invalid_event_type(cloud: Cloud):
    """Test that subscribing to an invalid event type raises an error."""
    subscriber = AsyncMock()

    with pytest.raises(EventBusError, match="Unknown event type: invalid_event"):
        cloud.events.subscribe(event_type="invalid_event", handler=subscriber)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dispatcher_message_on_publish(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that dispatcher message is sent when event is published."""
    subscriber = AsyncMock()

    cloud.events.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=subscriber
    )

    event = RelayerConnectedEvent()
    await cloud.events.publish(event=event)

    assert len(cloud.client.mock_dispatcher) == 1
    assert cloud.client.mock_dispatcher[0][0] == "event_relayer_connected"
    assert cloud.client.mock_dispatcher[0][1] == event
    assert extract_log_messages(caplog) == snapshot
