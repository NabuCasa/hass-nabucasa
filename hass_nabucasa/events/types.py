"""Event types for cloud system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from hass_nabucasa.iot_base import DisconnectReason


def _timestamp_factory() -> float:
    """Generate a timestamp for the current time."""
    return datetime.now(UTC).timestamp()


@dataclass(kw_only=True)
class _CloudEventBase:
    """Base class for all cloud events."""

    timestamp: float = field(default_factory=_timestamp_factory)


@dataclass(kw_only=True)
class RelayerConnectedEvent(_CloudEventBase):
    """Relayer connected event."""

    type: Literal["relayer_connected"] = "relayer_connected"


@dataclass(kw_only=True)
class RelayerDisconnectedEvent(_CloudEventBase):
    """Relayer disconnected event."""

    type: Literal["relayer_disconnected"] = "relayer_disconnected"
    reason: DisconnectReason | None = None


CloudEvent = RelayerConnectedEvent | RelayerDisconnectedEvent
type CloudEventType = Literal["relayer_connected", "relayer_disconnected"]
