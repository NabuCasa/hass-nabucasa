"""Central event bus."""

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import logging

from .types import CloudEvent, CloudEventType

_LOGGER = logging.getLogger(__name__)


class CloudEventBus:
    """Central event bus for all cloud events."""

    def __init__(self) -> None:
        """Initialize the event bus."""
        self._subscribers: dict[
            str,
            list[Callable[[CloudEvent], Awaitable[None]]],
        ] = {}

    def subscribe(
        self,
        *,
        event_type: CloudEventType | list[CloudEventType],
        handler: Callable[[CloudEvent], Awaitable[None]],
    ) -> Callable[[], None]:
        """Subscribe to an event type or list of event types."""
        event_types = [event_type] if isinstance(event_type, str) else event_type

        for evt_type in event_types:
            self._subscribers.setdefault(evt_type, []).append(handler)

        def unsubscribe() -> None:
            """Remove this subscription."""
            for evt_type in event_types:
                with contextlib.suppress(ValueError):
                    self._subscribers[evt_type].remove(handler)

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

        for handler, result in zip(handlers, results, strict=False):
            if isinstance(result, Exception):
                _LOGGER.warning(
                    "Error in event handler %s for event %s",
                    handler.__name__,
                    event_type,
                    exc_info=result,
                )
