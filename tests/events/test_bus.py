"""Tests for event bus."""

from unittest.mock import AsyncMock

import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa.events import CloudEventBus
from hass_nabucasa.events.types import (
    RelayerConnectedEvent,
    RelayerDisconnectedEvent,
)
from tests.common import extract_log_messages


@pytest.mark.asyncio
async def test_subscribe_and_publish(
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test basic subscription and publishing."""
    subscriber = AsyncMock()
    event_bus = CloudEventBus()

    unsubscribe = event_bus.subscribe(
        event_type="relayer_connected", handler=subscriber
    )

    await event_bus.publish(event=RelayerConnectedEvent())

    assert len(subscriber.call_args_list) == 1

    unsubscribe()

    assert subscriber.call_args_list == snapshot
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_publish_without_data(
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test publishing without extra fields."""
    subscriber = AsyncMock()
    event_bus = CloudEventBus()

    event_bus.subscribe(event_type="relayer_connected", handler=subscriber)

    event = RelayerConnectedEvent()
    await event_bus.publish(event=event)

    assert len(subscriber.call_args_list) == 1
    assert subscriber.call_args_list[0][0][0].type == "relayer_connected"
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_publish_without_subscribers(
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test publishing without any subscribers doesn't raise."""
    event_bus = CloudEventBus()

    event = RelayerConnectedEvent()
    await event_bus.publish(event=event)

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_unsubscribe(
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test unsubscribing from events."""
    subscriber = AsyncMock()
    event_bus = CloudEventBus()

    unsubscribe = event_bus.subscribe(
        event_type="relayer_connected", handler=subscriber
    )

    await event_bus.publish(event=RelayerConnectedEvent())
    assert len(subscriber.call_args_list) == 1

    unsubscribe()

    await event_bus.publish(event=RelayerConnectedEvent())
    assert len(subscriber.call_args_list) == 1

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_unsubscribe_multiple_times(
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that unsubscribing multiple times doesn't raise."""
    subscriber = AsyncMock()
    event_bus = CloudEventBus()

    unsubscribe = event_bus.subscribe(
        event_type="relayer_connected", handler=subscriber
    )

    unsubscribe()
    unsubscribe()

    await event_bus.publish(event=RelayerConnectedEvent())
    assert len(subscriber.call_args_list) == 0

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_error_handling(
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that errors in handlers don't stop other handlers."""
    failing_subscriber = AsyncMock(side_effect=ValueError("Test error"))
    working_subscriber = AsyncMock()
    event_bus = CloudEventBus()

    event_bus.subscribe(event_type="relayer_connected", handler=failing_subscriber)
    event_bus.subscribe(event_type="relayer_connected", handler=working_subscriber)

    await event_bus.publish(event=RelayerConnectedEvent())

    assert len(failing_subscriber.call_args_list) == 1
    assert len(working_subscriber.call_args_list) == 1
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_multiple_event_types(
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test subscribing to different event types."""
    connected_subscriber = AsyncMock()
    disconnected_subscriber = AsyncMock()
    event_bus = CloudEventBus()

    event_bus.subscribe(event_type="relayer_connected", handler=connected_subscriber)
    event_bus.subscribe(
        event_type="relayer_disconnected", handler=disconnected_subscriber
    )

    await event_bus.publish(event=RelayerConnectedEvent())
    await event_bus.publish(event=RelayerDisconnectedEvent())

    assert len(connected_subscriber.call_args_list) == 1
    assert len(disconnected_subscriber.call_args_list) == 1
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_multiple_subscribers(
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test multiple subscribers to the same event."""
    subscriber1 = AsyncMock()
    subscriber2 = AsyncMock()
    subscriber3 = AsyncMock()
    event_bus = CloudEventBus()

    event_bus.subscribe(event_type="relayer_connected", handler=subscriber1)
    event_bus.subscribe(event_type="relayer_connected", handler=subscriber2)
    event_bus.subscribe(event_type="relayer_connected", handler=subscriber3)

    await event_bus.publish(event=RelayerConnectedEvent())

    assert len(subscriber1.call_args_list) == 1
    assert len(subscriber2.call_args_list) == 1
    assert len(subscriber3.call_args_list) == 1
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_event_timestamp(
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that events have timestamps."""
    subscriber = AsyncMock()
    event_bus = CloudEventBus()

    event_bus.subscribe(event_type="relayer_connected", handler=subscriber)

    await event_bus.publish(event=RelayerConnectedEvent())

    assert len(subscriber.call_args_list) == 1
    assert subscriber.call_args_list[0][0][0].timestamp is not None
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.asyncio
async def test_subscribe_to_multiple_event_types(
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test subscribing to multiple event types with a single handler."""
    subscriber = AsyncMock()
    event_bus = CloudEventBus()

    unsubscribe = event_bus.subscribe(
        event_type=["relayer_connected", "relayer_disconnected"], handler=subscriber
    )

    await event_bus.publish(event=RelayerConnectedEvent())
    await event_bus.publish(event=RelayerDisconnectedEvent())

    assert len(subscriber.call_args_list) == 2
    assert subscriber.call_args_list[0][0][0].type == "relayer_connected"
    assert subscriber.call_args_list[1][0][0].type == "relayer_disconnected"

    unsubscribe()

    await event_bus.publish(event=RelayerConnectedEvent())
    assert len(subscriber.call_args_list) == 2

    assert extract_log_messages(caplog) == snapshot
