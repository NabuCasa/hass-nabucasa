"""Event types for cloud system."""

from enum import StrEnum


class CloudEventType(StrEnum):
    """All cloud events with clear relayer vs snitun distinction."""

    ALEXA_DISABLED = "alexa_disabled"
    ALEXA_ENABLED = "alexa_enabled"
    CLOUDHOOKS_UPDATED = "cloudhooks_updated"
    ERROR_OCCURRED = "error_occurred"
    GOOGLE_DISABLED = "google_disabled"
    GOOGLE_ENABLED = "google_enabled"
    LOGIN_FAILED = "login_failed"
    LOGIN_SUCCESS = "login_success"
    LOGOUT = "logout"
    RELAYER_CONNECTED = "relayer_connected"
    RELAYER_CONNECTING = "relayer_connecting"
    RELAYER_CONNECTION_FAILED = "relayer_connection_failed"
    RELAYER_DISCONNECTED = "relayer_disconnected"
    RELAYER_MESSAGE_RECEIVED = "relayer_message_received"
    RELAYER_MESSAGE_SENT = "relayer_message_sent"
    SNITUN_CERTIFICATE_UPDATED = "snitun_certificate_updated"
    SNITUN_CONNECTED = "snitun_connected"
    SNITUN_CONNECTING = "snitun_connecting"
    SNITUN_CONNECTION_FAILED = "snitun_connection_failed"
    SNITUN_DISCONNECTED = "snitun_disconnected"
    SUBSCRIPTION_CHANGED = "subscription_changed"
    SUBSCRIPTION_EXPIRED = "subscription_expired"
    TOKEN_REFRESH_FAILED = "token_refresh_failed"  # noqa: S105
    TOKEN_REFRESHED = "token_refreshed"  # noqa: S105
    WEBRTC_ICE_SERVERS_FAILED = "webrtc_ice_servers_failed"
    WEBRTC_ICE_SERVERS_REGISTERED = "webrtc_ice_servers_registered"
    WEBRTC_ICE_SERVERS_UPDATED = "webrtc_ice_servers_updated"
