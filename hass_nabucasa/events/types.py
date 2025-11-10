"""Event types for cloud system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from ..utils import utcnow

if TYPE_CHECKING:
    from ..iot_base import DisconnectReason


def _timestamp_factory() -> float:
    """Generate a timestamp for the current time."""
    return utcnow().timestamp()


class CloudEventType(StrEnum):
    """Cloud event types."""

    RELAYER_CONNECTED = "relayer_connected"
    RELAYER_DISCONNECTED = "relayer_disconnected"


@dataclass(kw_only=True, frozen=True)
class CloudEvent:
    """Base class for all cloud events."""

    timestamp: float = field(default_factory=_timestamp_factory)
    type: CloudEventType = field(init=False)


@dataclass(kw_only=True, frozen=True)
class RelayerConnectedEvent(CloudEvent):
    """Relayer connected event."""

    type = CloudEventType.RELAYER_CONNECTED


@dataclass(kw_only=True, frozen=True)
class RelayerDisconnectedEvent(CloudEvent):
    """Relayer disconnected event."""

    type = CloudEventType.RELAYER_DISCONNECTED
    reason: DisconnectReason | None = None
