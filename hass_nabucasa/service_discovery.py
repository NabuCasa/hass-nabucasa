"""Service discovery."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any, Literal, TypedDict, get_args

import voluptuous as vol

from .api import ApiBase, CloudApiError, api_exception_handler
from .const import (
    FIVE_MINUTES_IN_SECONDS,
    ONE_HOUR_IN_SECONDS,
    TWELVE_HOURS_IN_SECONDS,
)
from .utils import jitter, seconds_as_dhms, utcnow

if TYPE_CHECKING:
    from . import Cloud, _ClientT

_LOGGER = logging.getLogger(__name__)

MIN_REFRESH_INTERVAL = 60
TIME_DELTA_FOR_INITIAL_LOAD_RETRY = TWELVE_HOURS_IN_SECONDS

ServiceDiscoveryAction = Literal[
    "acme_directory",
    "llm_connection_details",
    "relayer_connect",
    "remote_access_resolve_dns_cname",
    "subscription_info",
    "subscription_migrate_paypal",
    "voice_connection_details",
]

VALID_ACTION_NAMES = frozenset(get_args(ServiceDiscoveryAction))


def _filter_and_validate_actions(actions: dict[str, Any]) -> dict[str, str]:
    """Filter actions to only known keys and validate they are valid URLs."""
    if not isinstance(actions, dict):
        raise vol.Invalid("actions must be a dictionary")

    filtered = {}
    for key in VALID_ACTION_NAMES:
        if not (value := actions.get(key)):
            raise vol.Invalid(f"Action '{key}' is missing")

        try:
            vol.Url(value)
        except vol.Invalid as err:
            raise vol.Invalid(f"Action '{key}' has invalid URL: {err}") from err
        filtered[key] = value

    return filtered


SERVICE_DISCOVERY_SCHEMA = vol.Schema(
    {
        vol.Required("actions"): _filter_and_validate_actions,
        vol.Required("valid_for"): vol.All(int, vol.Range(min=0)),
        vol.Required("version"): str,
    },
    extra=vol.REMOVE_EXTRA,
)


class ServiceDiscoveryError(CloudApiError):
    """Exception raised when handling service discovery API."""


class ServiceDiscoveryInvalidResponseError(ServiceDiscoveryError):
    """Exception raised when service discovery API returns invalid data."""


class ServiceDiscoveryMissingParameterError(ServiceDiscoveryError):
    """Exception raised when required format parameters are missing."""


class ServiceDiscoveryMissingActionError(ServiceDiscoveryError):
    """Exception raised when an action has no URL configured."""


class ServiceDiscoveryResponse(TypedDict):
    """Response from service discovery API."""

    actions: dict[str, str]
    valid_for: int
    version: str


class ServiceDiscoveryCacheData(TypedDict):
    """Cached service discovery data."""

    data: ServiceDiscoveryResponse
    valid_until: float


def _is_cache_valid(cache: ServiceDiscoveryCacheData) -> bool:
    """Check if cache is still valid."""
    try:
        return cache["valid_until"] > utcnow().timestamp()
    except (KeyError, TypeError):
        return False


def _calculate_sleep_time(valid_until: float) -> int:
    """Calculate sleep time until next refresh."""
    remaining = valid_until - utcnow().timestamp()

    # For expired or very soon expiring caches, spread refreshes over 1-5 min
    if remaining <= MIN_REFRESH_INTERVAL:
        return round(jitter(MIN_REFRESH_INTERVAL, FIVE_MINUTES_IN_SECONDS))

    return round(
        max(MIN_REFRESH_INTERVAL, remaining + jitter(5, ONE_HOUR_IN_SECONDS)),
    )


class ServiceDiscovery(ApiBase):
    """Class to handle service discovery."""

    def __init__(
        self,
        cloud: Cloud[_ClientT],
        *,
        action_overrides: dict[ServiceDiscoveryAction, str] | None = None,
    ) -> None:
        """Initialize service discovery."""
        super().__init__(cloud)
        self._load_service_discovery_data_lock = asyncio.Lock()
        self._service_discovery_refresh_task: asyncio.Task[None] | None = None
        self._memory_cache: ServiceDiscoveryCacheData | None = None
        self._action_overrides = action_overrides or {}

        if TYPE_CHECKING:
            assert self._cloud.accounts_server is not None
            assert self._cloud.relayer_server is not None
            assert self._cloud.servicehandlers_server is not None

        self._fallback_actions: dict[ServiceDiscoveryAction, str] = {
            "acme_directory": f"https://{self._cloud.acme_server}/directory",
            "llm_connection_details": f"https://{self._cloud.api_server}/llm/connection_details",
            "relayer_connect": f"wss://{self._cloud.relayer_server}/websocket",
            "remote_access_resolve_dns_cname": f"https://{self._cloud.accounts_server}/instance/resolve_dns_cname",
            "subscription_info": f"https://{self._cloud.accounts_server}/payments/subscription_info",
            "subscription_migrate_paypal": f"https://{self._cloud.accounts_server}/payments/migrate_paypal_agreement",
            "voice_connection_details": f"https://{self._cloud.servicehandlers_server}/voice/connection_details",
        }

    @property
    def hostname(self) -> str:
        """Get the hostname for service discovery."""
        if TYPE_CHECKING:
            assert self._cloud.api_server is not None
        return self._cloud.api_server

    @api_exception_handler(ServiceDiscoveryError)
    async def _fetch_well_known_service_discovery(self) -> ServiceDiscoveryResponse:
        """Fetch service discovery data from the well-known API."""
        validated_data: dict[str, Any] = await self._call_cloud_api(
            path="/.well-known/service-discovery",
            schema=SERVICE_DISCOVERY_SCHEMA,
            skip_token_check=True,
        )
        _LOGGER.debug(
            "Service discovery %s with %d actions fetched",
            validated_data["version"],
            len(validated_data["actions"]),
        )
        return ServiceDiscoveryResponse(
            actions=validated_data["actions"],
            valid_for=validated_data["valid_for"],
            version=validated_data["version"],
        )

    async def _load_service_discovery_data(self) -> ServiceDiscoveryCacheData:
        """Load discovery data from cache or fetch from API."""
        async with self._load_service_discovery_data_lock:
            cache = self._memory_cache

            if cache is not None and _is_cache_valid(cache):
                _LOGGER.debug("Using cached service discovery data")
                return cache

            try:
                discovery_data = await self._fetch_well_known_service_discovery()
            except ServiceDiscoveryError:
                if not cache:
                    raise

                _LOGGER.info(
                    "Unable to fetch service discovery data, using expired cache"
                )
                return cache

            cache_data = ServiceDiscoveryCacheData(
                data=discovery_data,
                valid_until=utcnow().timestamp() + discovery_data["valid_for"],
            )
            self._memory_cache = cache_data

            _LOGGER.debug(
                "Service discovery data cached, valid for %s",
                seconds_as_dhms(discovery_data["valid_for"]),
            )

            return cache_data

    async def async_start_service_discovery(self) -> None:
        """Start service discovery and wait for initial load."""
        if (
            self._service_discovery_refresh_task is None
            or self._service_discovery_refresh_task.done()
        ):
            try:
                await self._load_service_discovery_data()
            except ServiceDiscoveryError as err:
                _LOGGER.debug("Failed to load initial service discovery data: %s", err)

            self._service_discovery_refresh_task = asyncio.create_task(
                self._schedule_service_discovery_refresh(),
                name="service_discovery_refresh",
            )

    async def _schedule_service_discovery_refresh(self) -> None:
        """Schedule automatic refresh of service discovery data."""
        while True:
            try:
                if self._memory_cache is None:
                    # If we get here the initial load failed, retry after fixed delay
                    next_check = (
                        utcnow().timestamp() + TIME_DELTA_FOR_INITIAL_LOAD_RETRY
                    )
                else:
                    next_check = self._memory_cache["valid_until"]

                sleep_time = _calculate_sleep_time(next_check)

                _LOGGER.debug(
                    "Scheduling service discovery refresh in %s",
                    seconds_as_dhms(sleep_time),
                )
                await asyncio.sleep(sleep_time)

                await self._load_service_discovery_data()
            except asyncio.CancelledError:
                _LOGGER.debug("Service discovery refresh task cancelled")
                raise
            except ServiceDiscoveryError as err:
                _LOGGER.info("Unable to refresh service discovery data: %s", err)

    async def async_stop_service_discovery(self) -> None:
        """Stop the service discovery component."""
        if (
            self._service_discovery_refresh_task is not None
            and not self._service_discovery_refresh_task.done()
        ):
            self._service_discovery_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._service_discovery_refresh_task
            self._service_discovery_refresh_task = None

    def _get_fallback_action_url(self, action: ServiceDiscoveryAction) -> str:
        """Get fallback action."""
        if (fallback_action_url := self._fallback_actions.get(action)) is not None:
            _LOGGER.info(
                "Using fallback action URL for %s: %s", action, fallback_action_url
            )
            return fallback_action_url
        raise ServiceDiscoveryMissingActionError(
            f"No fallback URL for action: {action}"
        )

    def _get_service_action_url(self, action: ServiceDiscoveryAction) -> str:
        """Get URL for a specific action."""
        if action_override_url := self._action_overrides.get(action):
            _LOGGER.info(
                "Using overridden action URL for %s: %s", action, action_override_url
            )
            return action_override_url

        if self._memory_cache and (
            cached_action_url := self._memory_cache["data"]["actions"].get(action)
        ):
            _LOGGER.debug(
                "Using cached action URL for %s: %s", action, cached_action_url
            )
            return cached_action_url
        return self._get_fallback_action_url(action)

    def action_url(self, action: ServiceDiscoveryAction, **kwargs: str) -> str:
        """Get URL for a specific action with optional format parameters."""
        if action not in VALID_ACTION_NAMES:
            raise ServiceDiscoveryMissingActionError(f"Unknown action: {action}")

        try:
            return self._get_service_action_url(action).format_map(kwargs)
        except KeyError as err:
            raise ServiceDiscoveryMissingParameterError(
                f"Missing required format parameter {err} for action '{action}'"
            ) from err
