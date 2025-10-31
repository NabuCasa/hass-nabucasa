"""Tests for event bus."""

import pytest

from hass_nabucasa.events import CloudEvent, CloudEventBus, CloudEventType


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    """Test basic subscription and publishing."""
    bus = CloudEventBus()
    received_events = []

    async def handler(event: CloudEvent) -> None:
        received_events.append(event)

    unsubscribe = bus.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=handler
    )

    await bus.publish(
        event_type=CloudEventType.RELAYER_CONNECTED,
        data={"foo": "bar"},
    )

    assert len(received_events) == 1
    assert received_events[0].type == CloudEventType.RELAYER_CONNECTED
    assert received_events[0].data == {"foo": "bar"}

    unsubscribe()


@pytest.mark.asyncio
async def test_publish_without_data():
    """Test publishing without data."""
    bus = CloudEventBus()
    received_events = []

    async def handler(event: CloudEvent) -> None:
        received_events.append(event)

    bus.subscribe(event_type=CloudEventType.RELAYER_CONNECTED, handler=handler)

    await bus.publish(event_type=CloudEventType.RELAYER_CONNECTED)

    assert len(received_events) == 1
    assert received_events[0].data == {}


@pytest.mark.asyncio
async def test_publish_without_subscribers():
    """Test publishing without any subscribers doesn't raise."""
    bus = CloudEventBus()

    await bus.publish(event_type=CloudEventType.RELAYER_CONNECTED)


@pytest.mark.asyncio
async def test_unsubscribe():
    """Test unsubscribing from events."""
    bus = CloudEventBus()
    received_events = []

    async def handler(event: CloudEvent) -> None:
        received_events.append(event)

    unsubscribe = bus.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=handler
    )

    await bus.publish(event_type=CloudEventType.RELAYER_CONNECTED)
    assert len(received_events) == 1

    unsubscribe()

    await bus.publish(event_type=CloudEventType.RELAYER_CONNECTED)
    assert len(received_events) == 1


@pytest.mark.asyncio
async def test_unsubscribe_multiple_times():
    """Test that unsubscribing multiple times doesn't raise."""
    bus = CloudEventBus()
    received_events = []

    async def handler(event: CloudEvent) -> None:
        received_events.append(event)

    unsubscribe = bus.subscribe(
        event_type=CloudEventType.RELAYER_CONNECTED, handler=handler
    )

    unsubscribe()
    unsubscribe()

    await bus.publish(event_type=CloudEventType.RELAYER_CONNECTED)
    assert len(received_events) == 0


@pytest.mark.asyncio
async def test_error_handling():
    """Test that errors in handlers don't stop other handlers."""
    bus = CloudEventBus()
    successful_calls = []

    async def failing_handler(event: CloudEvent) -> None:
        raise ValueError("Test error")

    async def working_handler(event: CloudEvent) -> None:
        successful_calls.append(event)

    bus.subscribe(event_type=CloudEventType.RELAYER_CONNECTED, handler=failing_handler)
    bus.subscribe(event_type=CloudEventType.RELAYER_CONNECTED, handler=working_handler)

    await bus.publish(event_type=CloudEventType.RELAYER_CONNECTED)

    assert len(successful_calls) == 1


@pytest.mark.asyncio
async def test_multiple_event_types():
    """Test subscribing to different event types."""
    bus = CloudEventBus()
    relayer_events = []
    snitun_events = []

    async def relayer_handler(event: CloudEvent) -> None:
        relayer_events.append(event)

    async def snitun_handler(event: CloudEvent) -> None:
        snitun_events.append(event)

    bus.subscribe(event_type=CloudEventType.RELAYER_CONNECTED, handler=relayer_handler)
    bus.subscribe(event_type=CloudEventType.SNITUN_CONNECTED, handler=snitun_handler)

    await bus.publish(event_type=CloudEventType.RELAYER_CONNECTED)
    await bus.publish(event_type=CloudEventType.SNITUN_CONNECTED)

    assert len(relayer_events) == 1
    assert len(snitun_events) == 1


@pytest.mark.asyncio
async def test_multiple_subscribers():
    """Test multiple subscribers to the same event."""
    bus = CloudEventBus()
    call_count = [0, 0, 0]

    async def handler1(event: CloudEvent) -> None:
        call_count[0] += 1

    async def handler2(event: CloudEvent) -> None:
        call_count[1] += 1

    async def handler3(event: CloudEvent) -> None:
        call_count[2] += 1

    bus.subscribe(event_type=CloudEventType.RELAYER_CONNECTED, handler=handler1)
    bus.subscribe(event_type=CloudEventType.RELAYER_CONNECTED, handler=handler2)
    bus.subscribe(event_type=CloudEventType.RELAYER_CONNECTED, handler=handler3)

    await bus.publish(event_type=CloudEventType.RELAYER_CONNECTED)

    assert call_count == [1, 1, 1]


@pytest.mark.asyncio
async def test_event_timestamp():
    """Test that events have timestamps."""
    bus = CloudEventBus()
    received_events = []

    async def handler(event: CloudEvent) -> None:
        received_events.append(event)

    bus.subscribe(event_type=CloudEventType.RELAYER_CONNECTED, handler=handler)

    await bus.publish(event_type=CloudEventType.RELAYER_CONNECTED)

    assert len(received_events) == 1
    assert received_events[0].timestamp is not None
