"""Event types for cloud system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from ..utils import utcnow

if TYPE_CHECKING:
    from ..cloudhooks import CloudhookDetails
    from ..iot_base import DisconnectReason


def _timestamp_factory() -> float:
    """Generate a timestamp for the current time."""
    return utcnow().timestamp()


class CloudEventType(StrEnum):
    """Cloud event types."""

    CLOUDHOOK_CREATED = "cloudhook_created"
    CLOUDHOOK_DELETED = "cloudhook_deleted"
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
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
class CloudhookCreatedEvent(CloudEvent):
    """Cloudhook created event."""

    type: CloudEventType = field(default=CloudEventType.CLOUDHOOK_CREATED, init=False)
    cloudhook: CloudhookDetails


@dataclass(kw_only=True, frozen=True)
class CloudhookDeletedEvent(CloudEvent):
    """Cloudhook deleted event."""

    type: CloudEventType = field(default=CloudEventType.CLOUDHOOK_DELETED, init=False)
    cloudhook: CloudhookDetails


class LoginFailedReason(StrEnum):
    """Reason the register-and-auto-login flow gave up without logging in."""

    TIMEOUT = "timeout"
    CLOUD_ERROR = "cloud_error"
    UNEXPECTED_ERROR = "unexpected_error"


@dataclass(kw_only=True, frozen=True)
class LoginEvent(CloudEvent):
    """Login succeeded event."""

    type: CloudEventType = field(default=CloudEventType.LOGIN, init=False)
    auto: bool = False


@dataclass(kw_only=True, frozen=True)
class LoginFailedEvent(CloudEvent):
    """Login failed event."""

    type: CloudEventType = field(default=CloudEventType.LOGIN_FAILED, init=False)
    reason: LoginFailedReason
    auto: bool = False


@dataclass(kw_only=True, frozen=True)
class LogoutEvent(CloudEvent):
    """Logout event."""

    type: CloudEventType = field(default=CloudEventType.LOGOUT, init=False)
