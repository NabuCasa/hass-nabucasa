"""Central event bus."""

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any

from .types import CloudEventType

_LOGGER = logging.getLogger(__name__)


@dataclass
class CloudEvent:
    """Event that occurred in the cloud system."""

    type: CloudEventType
    data: dict[str, Any]
    timestamp: datetime


class CloudEventBus:
    """Central event bus for all cloud events."""

    def __init__(self) -> None:
        """Initialize the event bus."""
        self._subscribers: dict[
            CloudEventType,
            list[Callable[[CloudEvent], Awaitable[None]]],
        ] = {}

    def subscribe(
        self,
        *,
        event_type: CloudEventType,
        handler: Callable[[CloudEvent], Awaitable[None]],
        **_: Any,
    ) -> Callable[[], None]:
        """Subscribe to an event type."""
        self._subscribers.setdefault(event_type, []).append(handler)

        def unsubscribe() -> None:
            """Remove this subscription."""
            with contextlib.suppress(ValueError):
                self._subscribers[event_type].remove(handler)

        return unsubscribe

    async def publish(
        self,
        *,
        event_type: CloudEventType,
        data: dict[str, Any] | None = None,
        **_: Any,
    ) -> None:
        """Publish an event to all subscribers."""
        event = CloudEvent(
            type=event_type,
            data=data or {},
            timestamp=datetime.now(UTC),
        )

        if event_type not in self._subscribers:
            return

        handlers = self._subscribers[event_type]

        _LOGGER.debug(
            "Publishing event %s to %d subscribers", event_type.name, len(handlers)
        )

        results = await asyncio.gather(
            *[handler(event) for handler in handlers],
            return_exceptions=True,
        )

        for handler, result in zip(handlers, results, strict=False):
            if isinstance(result, Exception):
                _LOGGER.exception(
                    "Error in event handler %s for event %s",
                    handler.__name__,
                    event_type.name,
                    exc_info=result,
                )
