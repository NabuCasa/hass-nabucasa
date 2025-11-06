"""Central event bus."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import logging

from ..exceptions import CloudError
from .types import CloudEvent, CloudEventType

_LOGGER = logging.getLogger(__name__)


class EventBusError(CloudError):
    """Exception raised for event bus errors."""


class CloudEventBus:
    """Central event bus for all cloud events."""

    def __init__(self) -> None:
        """Initialize the event bus."""
        self._subscribers: dict[
            str,
            list[Callable[[CloudEvent], Awaitable[None]]],
        ] = {k.value: [] for k in CloudEventType}

    def subscribe(
        self,
        *,
        event_type: CloudEventType | list[CloudEventType],
        handler: Callable[[CloudEvent], Awaitable[None]],
    ) -> Callable[[], None]:
        """Subscribe to an event type or list of event types."""
        event_types = event_type if isinstance(event_type, list) else [event_type]

        for evt_type in event_types:
            if evt_type not in self._subscribers:
                raise EventBusError(f"Unknown event type: {evt_type}")
            self._subscribers[evt_type].append(handler)

        _LOGGER.debug("%s subscribed to %s", handler.__name__, event_types)

        def unsubscribe() -> None:
            """Remove this subscription."""
            for evt_type in event_types:
                with contextlib.suppress(ValueError):
                    self._subscribers[evt_type].remove(handler)
            _LOGGER.debug("%s unsubscribed from %s", handler.__name__, event_types)

        return unsubscribe

    async def publish(
        self,
        event: CloudEvent,
    ) -> None:
        """Publish an event to all subscribers."""
        event_type = event.type

        if event_type not in self._subscribers:
            return

        handlers = self._subscribers[event_type]

        if not handlers:
            _LOGGER.debug("No subscribers for event %s", event_type)
            return

        _LOGGER.debug("Publish %s to %d subscribers", event_type, len(handlers))

        results = await asyncio.gather(
            *[handler(event) for handler in handlers],
            return_exceptions=True,
        )

        for handler, result in zip(handlers, results, strict=True):
            if isinstance(result, Exception):
                _LOGGER.error(
                    "Error in event handler %s for event %s",
                    handler.__name__,
                    event_type,
                    exc_info=result,
                )
