"""Helper methods to handle the time in Home Assistant."""
import datetime as dt
import ssl
from typing import Optional, Callable, TypeVar

import pytz

CALLABLE_T = TypeVar("CALLABLE_T", bound=Callable)  # noqa pylint: disable=invalid-name
DATE_STR_FORMAT = "%Y-%m-%d"
UTC = pytz.utc


def utcnow() -> dt.datetime:
    """Get now in UTC time."""
    return dt.datetime.now(UTC)


def utc_from_timestamp(timestamp: float) -> dt.datetime:
    """Return a UTC time from a timestamp."""
    return UTC.localize(dt.datetime.utcfromtimestamp(timestamp))


def parse_date(dt_str: str) -> Optional[dt.date]:
    """Convert a date string to a date object."""
    try:
        return dt.datetime.strptime(dt_str, DATE_STR_FORMAT).date()
    except ValueError:  # If dt_str did not match our format
        return None


def server_context_modern() -> ssl.SSLContext:
    """Return an SSL context following the Mozilla recommendations.
    TLS configuration follows the best-practice guidelines specified here:
    https://wiki.mozilla.org/Security/Server_Side_TLS
    Modern guidelines are followed.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS)  # pylint: disable=no-member

    context.options |= (
        ssl.OP_NO_SSLv2
        | ssl.OP_NO_SSLv3
        | ssl.OP_NO_TLSv1
        | ssl.OP_NO_TLSv1_1
        | ssl.OP_CIPHER_SERVER_PREFERENCE
    )
    if hasattr(ssl, "OP_NO_COMPRESSION"):
        context.options |= ssl.OP_NO_COMPRESSION

    context.set_ciphers(
        "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
        "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
        "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
        "ECDHE-ECDSA-AES256-SHA384:ECDHE-RSA-AES256-SHA384:"
        "ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256"
    )

    return context


def next_midnight() -> int:
    """Return the seconds till next local midnight."""
    midnight = dt.datetime.now().replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + dt.timedelta(days=1)
    return (midnight - dt.datetime.now()).total_seconds()


class Registry(dict):
    """Registry of items."""

    def register(self, name: str) -> Callable[[CALLABLE_T], CALLABLE_T]:
        """Return decorator to register item with a specific name."""

        def decorator(func: CALLABLE_T) -> CALLABLE_T:
            """Register decorated function."""
            self[name] = func
            return func

        return decorator
