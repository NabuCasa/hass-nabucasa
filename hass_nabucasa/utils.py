"""Helper methods to handle the time in Home Assistant."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import datetime as dt
import logging
from logging import Logger
import random
import ssl
from typing import Any, TypedDict, TypeVar

import ciso8601
from icmplib import Host, ICMPLibError, SocketPermissionError, async_multiping
import jwt

from .exceptions import NabuCasaBaseError

CALLABLE_T = TypeVar("CALLABLE_T", bound=Callable)  # pylint: disable=invalid-name
UTC = dt.UTC

DEFAULT_BACKOFF_JITTER = 0.125
DEFAULT_BACKOFF_MULTIPLIER = 1.5

_LOGGER = logging.getLogger(__name__)


class CheckLatencyError(NabuCasaBaseError):
    """Error to indicate a ping failure."""


class CheckLatencyInsufficientPrivileges(CheckLatencyError):
    """Error to indicate insufficient privileges for pinging."""


class CheckLatencyHostResult(TypedDict):
    """Result of a latency check for a single host."""

    address: str
    avg_rtt: float
    is_alive: bool
    max_rtt: float
    min_rtt: float


def utcnow() -> dt.datetime:
    """Get now in UTC time."""
    return dt.datetime.now(UTC)


def utc_from_timestamp(timestamp: float) -> dt.datetime:
    """Return a UTC time from a timestamp."""
    return dt.datetime.fromtimestamp(timestamp, UTC)


def parse_date(dt_str: str) -> dt.date | None:
    """Convert a date string to a date object."""
    try:
        return ciso8601.parse_datetime(dt_str).date()
    except ValueError:  # If dt_str did not match our format
        return None


def seconds_as_dhms(seconds: float) -> str:
    """Convert seconds to a DDd:HHh:MMm:SSs string."""
    days, seconds = divmod(int(seconds), 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or (parts and (minutes > 0 or seconds > 0)):
        parts.append(f"{hours}h")
    if minutes > 0 or (parts and seconds > 0):
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")
    return ":".join(parts)


def expiration_from_token(token: str | None) -> int | None:
    """Return the expiration time from a token."""
    if not token:
        return None

    try:
        decoded_token: Mapping[str, Any] = jwt.decode(
            token,
            options={"verify_signature": False},
        )
        return int(decoded_token["exp"])
    except jwt.DecodeError, KeyError:
        return None


def server_context_modern() -> ssl.SSLContext:
    """
    Return an SSL context following the Mozilla recommendations.

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
        "ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256",
    )

    return context


def next_midnight() -> float:
    """Return the seconds till next local midnight."""
    midnight = dt.datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ) + dt.timedelta(days=1)
    return (midnight - dt.datetime.now()).total_seconds()


async def async_check_latency(
    addresses: list[str],
    *,
    count: int = 1,
    ping_timeout: float = 5,
    privileged: bool = True,
) -> list[CheckLatencyHostResult]:
    """Check latency to a list of IP addresses and return them.

    Args:
        addresses: List of IP addresses to ping.
        count: Number of ping packets to send to each address.
        ping_timeout: Timeout in seconds for each ping.
        privileged: Whether to use privileged (raw socket) mode.

    Returns:
        List of CheckLatencyHostResult dicts.

    """
    if not addresses:
        raise CheckLatencyError("No addresses provided")

    hosts: list[Host]
    try:
        hosts = await async_multiping(
            addresses=addresses,
            count=count,
            timeout=ping_timeout,
            privileged=privileged,
        )
    except SocketPermissionError as err:
        if not privileged:
            raise CheckLatencyInsufficientPrivileges(
                "Insufficient privileges to perform ICMP ping."
            ) from err
        _LOGGER.info(
            "Ping failed due to insufficient privileges, "
            "retrying without privileged mode"
        )
        return await async_check_latency(
            addresses,
            count=count,
            ping_timeout=ping_timeout,
            privileged=False,
        )
    except ICMPLibError as err:
        raise CheckLatencyError("ICMP ping failed") from err

    return [
        CheckLatencyHostResult(
            address=host.address,
            is_alive=host.is_alive,
            avg_rtt=host.avg_rtt,
            max_rtt=host.max_rtt,
            min_rtt=host.min_rtt,
        )
        for host in hosts
    ]


def jitter(minimum: float, maximum: float) -> float:
    """Return a random float between minimum and maximum for backoff jitter."""
    return random.uniform(minimum, maximum)


class Backoff:
    """Calculate the delays between the attempts of a retry loop.

    The class only calculates the delays, it does not sleep, so the caller
    stays in control of how it waits and of what it logs while waiting:

    ```python
    backoff = Backoff(initial=10, maximum=ONE_HOUR_IN_SECONDS)

    while True:
        if await do_the_thing():
            backoff.reset()
            continue

        interval = backoff.next_interval()
        _LOGGER.debug("Trying again in %s", seconds_as_dhms(interval))
        await asyncio.sleep(interval)
    ```

    An instance belongs to a single loop and is not safe to share between
    concurrent loops.
    """

    def __init__(
        self,
        *,
        initial: float,
        maximum: float,
        multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
        jitter_fraction: float = DEFAULT_BACKOFF_JITTER,
    ) -> None:
        """Initialize the backoff.

        Args:
            initial: Seconds to wait before the first retry. Keep it short so
                a transient failure recovers quickly, the growth handles the
                failures that are not transient.
            maximum: Upper bound in seconds for a single interval. The interval
                grows until it reaches this value and then stays there, so this
                is the slowest the loop will ever retry.
            multiplier: What the interval is multiplied by for every attempt.
                The default of 1.5 grows the interval by half each time (10s,
                15s, 22.5s, ...), which stays responsive for a while before it
                settles at the maximum. Use 1.0 for a fixed interval, or 2.0 to
                double the interval on every attempt.
            jitter_fraction: Fraction of the interval that is randomly shaved
                off it, between 0 and 1. The default of 0.125 spreads retries
                out by up to 12.5%, so instances that failed at the same time
                (a service outage) do not all retry in the same moment. It is
                subtracted rather than added so that an interval never passes
                the maximum, and it applies to the initial interval as well.
                Pass 0 to disable.

        Raises:
            ValueError: If an option is outside of its valid range.

        """
        if initial <= 0:
            raise ValueError("initial must be greater than 0")
        if maximum < initial:
            raise ValueError("maximum must not be smaller than initial")
        if multiplier < 1:
            raise ValueError("multiplier must not be smaller than 1")
        if not 0 <= jitter_fraction <= 1:
            raise ValueError("jitter_fraction must be between 0 and 1")

        self._initial = float(initial)
        self._maximum = float(maximum)
        self._multiplier = float(multiplier)
        self._jitter_fraction = float(jitter_fraction)

        self._attempts = 0
        self._elapsed = 0.0
        self._interval = self._initial

    @property
    def attempts(self) -> int:
        """Return the number of intervals handed out since the last reset."""
        return self._attempts

    @property
    def elapsed(self) -> float:
        """Return the accumulated delay handed out since the last reset."""
        return self._elapsed

    def reset(self) -> None:
        """Start over from the initial interval."""
        self._attempts = 0
        self._elapsed = 0.0
        self._interval = self._initial

    def next_interval(self) -> float:
        """Return the seconds to wait before the next attempt."""
        interval = self._interval
        if self._jitter_fraction:
            interval -= jitter(0, interval * self._jitter_fraction)

        self._attempts += 1
        self._elapsed += interval
        self._interval = min(self._interval * self._multiplier, self._maximum)
        return interval


async def gather_callbacks(
    logger: Logger,
    name: str,
    callbacks: list[Callable[[], Awaitable[None]]],
) -> None:
    """Gather callbacks and log exceptions."""
    results = await asyncio.gather(*[cb() for cb in callbacks], return_exceptions=True)
    for result, callback in zip(results, callbacks, strict=False):
        if not isinstance(result, Exception):
            continue
        logger.error(
            "Unexpected error in %s callback %s", name, callback, exc_info=result
        )


async def wait_for_event(event: asyncio.Event, timeout_seconds: float) -> bool:
    """Wait up to timeout_seconds for event to be set.

    Returns True if the event fired within the timeout, clearing it so it can be
    reused, or False if the timeout elapsed first.
    """
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
    except TimeoutError:
        return False
    event.clear()
    return True


class Registry(dict):
    """Registry of items."""

    def register(self, name: str) -> Callable[[CALLABLE_T], CALLABLE_T]:
        """Return decorator to register item with a specific name."""

        def decorator(func: CALLABLE_T) -> CALLABLE_T:
            """Register decorated function."""
            self[name] = func
            return func

        return decorator
