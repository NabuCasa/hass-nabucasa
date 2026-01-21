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

    LOGIN = "login"
    LOGOUT = "logout"
    RELAYER_CONNECTED = "relayer_connected"
    RELAYER_DISCONNECTED = "relayer_disconnected"
    SERVICE_DISCOVERY_UPDATE = "service_discovery_update"


@dataclass(kw_only=True, frozen=True)
class CloudEvent:
    """Base class for all cloud events."""

    type: CloudEventType
    timestamp: float = field(default_factory=_timestamp_factory)


@dataclass(kw_only=True, frozen=True)
class RelayerConnectedEvent(CloudEvent):
    """Relayer connected event."""

    type: CloudEventType = field(default=CloudEventType.RELAYER_CONNECTED, init=False)


@dataclass(kw_only=True, frozen=True)
class RelayerDisconnectedEvent(CloudEvent):
    """Relayer disconnected event."""

    type: CloudEventType = field(
        default=CloudEventType.RELAYER_DISCONNECTED, init=False
    )
    reason: DisconnectReason | None = None


@dataclass(kw_only=True, frozen=True)
class ServiceDiscoveryUpdateEvent(CloudEvent):
    """Service discovery update event."""

    type: CloudEventType = field(
        default=CloudEventType.SERVICE_DISCOVERY_UPDATE, init=False
    )
