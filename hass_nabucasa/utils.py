"""Helper methods to handle the time in Home Assistant."""
import asyncio
import datetime as dt
import logging
import pathlib
import ssl
import tempfile
from typing import Awaitable, Callable, List, Optional, TypeVar

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


async def gather_callbacks(
    logger: logging.Logger, name: str, callbacks: List[Callable[[], Awaitable[None]]]
) -> None:
    results = await asyncio.gather(*[cb() for cb in callbacks], return_exceptions=True)
    for result, callback in zip(results, callbacks):
        if not isinstance(result, Exception):
            continue
        logger.error("Unexpected error in %s %s", name, callback, exc_info=result)


class Registry(dict):
    """Registry of items."""

    def register(self, name: str) -> Callable[[CALLABLE_T], CALLABLE_T]:
        """Return decorator to register item with a specific name."""

        def decorator(func: CALLABLE_T) -> CALLABLE_T:
            """Register decorated function."""
            self[name] = func
            return func

        return decorator


def safe_write(
    filename: pathlib.Path, data: str, logger: logging.Logger, private=False
) -> None:
    """Write data to a file in a safe manner.

    Normal writes will truncate file, then try writing to it. This causes
    issues when the user runs out of disk space.
    """
    tmp_filename = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(filename.parent), delete=False
        ) as fdesc:
            fdesc.write(data)
            tmp_filename = pathlib.Path(fdesc.name)
        # Modern versions of Python tempfile create this file with mode 0o600
        if not private:
            tmp_filename.chmod(0o644)
        tmp_filename.replace(filename)
    finally:
        # Clean up in case of exceptions
        if tmp_filename and tmp_filename.is_file():
            try:
                tmp_filename.unlink()
            except OSError as err:
                logger.error("Cleanup failed: %s", err)
