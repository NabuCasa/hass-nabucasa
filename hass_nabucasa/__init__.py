"""Component to integrate the Home Assistant cloud."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
import random
import shutil
from typing import Any, Generic, Literal, TypeVar

from aiohttp import ClientSession
from atomicwrites import atomic_write
import jwt

from .account_api import AccountApi, AccountApiError
from .accounts_api import AccountsApi, AccountsApiError
from .alexa_api import (
    AlexaAccessTokenDetails,
    AlexaApi,
    AlexaApiError,
    AlexaApiNeedsRelinkError,
    AlexaApiNoTokenError,
)
from .api import (
    CloudApiClientError,
    CloudApiCodedError,
    CloudApiError,
    CloudApiNonRetryableError,
    CloudApiTimeoutError,
)
from .auth import CognitoAuth
from .client import CloudClient
from .cloudhooks import Cloudhooks
from .const import (
    ACCOUNT_URL,
    CONFIG_DIR,
    DEFAULT_SERVERS,
    DEFAULT_VALUES,
    MODE_DEV,
    STATE_CONNECTED,
    CertificateStatus,
    SubscriptionReconnectionReason,
)
from .exceptions import (
    CloudError,
    NabuCasaAuthenticationError,
    NabuCasaBaseError,
    NabuCasaConnectionError,
)
from .files import Files, FilesError, StorageType, StoredFile, calculate_b64md5
from .google_report_state import GoogleReportState, GoogleReportStateError
from .ice_servers import IceServers, IceServersApiError
from .instance_api import InstanceApi, InstanceApiError, InstanceConnectionDetails
from .iot import CloudIoT
from .payments_api import (
    MigratePaypalAgreementInfo,
    PaymentsApi,
    PaymentsApiError,
    SubscriptionInfo,
)
from .remote import RemoteUI
from .utils import UTC, gather_callbacks, parse_date, utcnow
from .voice import Voice
from .voice_api import VoiceApi, VoiceApiError

__all__ = [
    "MODE_DEV",
    "AccountApiError",
    "AccountsApi",
    "AccountsApiError",
    "AlexaAccessTokenDetails",
    "AlexaApiError",
    "AlexaApiNeedsRelinkError",
    "AlexaApiNoTokenError",
    "AlreadyConnectedError",
    "CertificateStatus",
    "Cloud",
    "CloudApiClientError",
    "CloudApiCodedError",
    "CloudApiError",
    "CloudApiNonRetryableError",
    "CloudApiTimeoutError",
    "CloudClient",
    "CloudError",
    "FilesError",
    "GoogleReportStateError",
    "IceServersApiError",
    "InstanceApiError",
    "InstanceConnectionDetails",
    "MigratePaypalAgreementInfo",
    "NabuCasaAuthenticationError",
    "NabuCasaBaseError",
    "NabuCasaConnectionError",
    "PaymentsApiError",
    "StorageType",
    "StoredFile",
    "SubscriptionInfo",
    "SubscriptionReconnectionReason",
    "VoiceApiError",
    "calculate_b64md5",
]

_ClientT = TypeVar("_ClientT", bound=CloudClient)


_LOGGER = logging.getLogger(__name__)


class AlreadyConnectedError(CloudError):
    """Raised when a connection is already established."""

    def __init__(self, *, details: InstanceConnectionDetails) -> None:
        """Initialize an already connected error."""
        super().__init__("instance_already_connected")
        self.details = details


class Cloud(Generic[_ClientT]):
    """Store the configuration of the cloud connection."""

    def __init__(
        self,
        client: _ClientT,
        mode: Literal["development", "production"],
        *,
        cognito_client_id: str | None = None,
        region: str | None = None,
        user_pool_id: str | None = None,
        account_link_server: str | None = None,
        accounts_server: str | None = None,
        acme_server: str | None = None,
        cloudhook_server: str | None = None,
        relayer_server: str | None = None,
        remotestate_server: str | None = None,
        servicehandlers_server: str | None = None,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Create an instance of Cloud."""
        self.client = client
        self.mode = mode

        self._on_initialized: list[Callable[[], Awaitable[None]]] = []
        self._on_start: list[Callable[[], Awaitable[None]]] = []
        self._on_stop: list[Callable[[], Awaitable[None]]] = []

        self._init_task: asyncio.Task | None = None
        self._subscription_reconnection_task: asyncio.Task | None = None

        self.access_token: str | None = None
        self.id_token: str | None = None
        self.refresh_token: str | None = None
        self.started: bool | None = None
        self._connection_retry_count = 0

        # Set reference
        self.client.cloud = self

        _values = DEFAULT_VALUES[mode]
        _servers = DEFAULT_SERVERS[mode]

        self.cognito_client_id = _values.get("cognito_client_id", cognito_client_id)
        self.region = _values.get("region", region)
        self.user_pool_id = _values.get("user_pool_id", user_pool_id)

        self.account_link_server = _servers.get("account_link", account_link_server)
        self.accounts_server = _servers.get("accounts", accounts_server)
        self.acme_server = _servers.get("acme", acme_server)
        self.cloudhook_server = _servers.get("cloudhook", cloudhook_server)
        self.relayer_server = _servers.get("relayer", relayer_server)
        self.remotestate_server = _servers.get("remotestate", remotestate_server)
        self.servicehandlers_server = _servers.get(
            "servicehandlers",
            servicehandlers_server,
        )

        # Needs to be setup before other components
        self.iot = CloudIoT(self)

        # Setup the rest of the components
        self.account = AccountApi(self)
        self.accounts = AccountsApi(self)
        self.alexa_api = AlexaApi(self)
        self.auth = CognitoAuth(self)
        self.cloudhooks = Cloudhooks(self)
        self.files = Files(self)
        self.google_report_state = GoogleReportState(self)
        self.ice_servers = IceServers(self)
        self.instance = InstanceApi(self)
        self.payments = PaymentsApi(self)
        self.remote = RemoteUI(self)
        self.voice = Voice(self)
        self.voice_api = VoiceApi(self)

    @property
    def is_logged_in(self) -> bool:
        """Get if cloud is logged in."""
        return self.id_token is not None

    @property
    def is_connected(self) -> bool:
        """Return True if we are connected."""
        return self.iot.state == STATE_CONNECTED

    @property
    def websession(self) -> ClientSession:
        """Return websession for connections."""
        return self.client.websession

    @property
    def subscription_expired(self) -> bool:
        """Return a boolean if the subscription has expired."""
        return utcnow() > self.expiration_date + timedelta(days=7)

    @property
    def valid_subscription(self) -> bool:
        """Return True if the subscription is valid."""
        return (
            self._subscription_reconnection_task is None
            and not self.subscription_expired
        )

    @property
    def expiration_date(self) -> datetime:
        """Return the subscription expiration as a UTC datetime object."""
        if (parsed_date := parse_date(self.claims["custom:sub-exp"])) is None:
            raise ValueError(
                f"Invalid expiration date ({self.claims['custom:sub-exp']})",
            )
        return datetime.combine(parsed_date, datetime.min.time()).replace(tzinfo=UTC)

    @property
    def username(self) -> str:
        """Return the subscription username."""
        return self.claims["cognito:username"]

    @property
    def claims(self) -> Mapping[str, str]:
        """Return the claims from the id token."""
        return self._decode_claims(str(self.id_token))

    @property
    def user_info_path(self) -> Path:
        """Get path to the stored auth."""
        return self.path(f"{self.mode}_auth.json")

    async def ensure_not_connected(
        self,
        *,
        access_token: str,
    ) -> None:
        """Raise AlreadyConnectedError if already connected."""
        try:
            connection = await self.instance.connection(
                skip_token_check=True,
                access_token=access_token,
            )
        except CloudError:
            return

        if connection["connected"]:
            raise AlreadyConnectedError(details=connection["details"])

    async def update_token(
        self,
        id_token: str,
        access_token: str,
        refresh_token: str | None = None,
    ) -> asyncio.Task | None:
        """Update the id and access token."""
        self.id_token = id_token
        self.access_token = access_token
        if refresh_token is not None:
            self.refresh_token = refresh_token

        await self.run_executor(self._write_user_info)

        if self.started is None:
            return None

        if not self.started and not self.subscription_expired:
            self.started = True
            return asyncio.create_task(self._start())

        if self.started and self.subscription_expired:
            self.started = False
            await self.stop()

        if self.subscription_expired:
            self.async_initialize_subscription_reconnection_handler(
                SubscriptionReconnectionReason.SUBSCRIPTION_EXPIRED
            )

        return None

    def register_on_initialized(
        self,
        on_initialized_cb: Callable[[], Awaitable[None]],
    ) -> None:
        """Register an async on_initialized callback.

        on_initialized callbacks are called after all on_start callbacks.
        """
        self._on_initialized.append(on_initialized_cb)

    def register_on_start(self, on_start_cb: Callable[[], Awaitable[None]]) -> None:
        """Register an async on_start callback."""
        self._on_start.append(on_start_cb)

    def register_on_stop(self, on_stop_cb: Callable[[], Awaitable[None]]) -> None:
        """Register an async on_stop callback."""
        self._on_stop.append(on_stop_cb)

    def path(self, *parts: Any) -> Path:
        """Get config path inside cloud dir.

        Async friendly.
        """
        return Path(self.client.base_path, CONFIG_DIR, *parts)

    def run_executor(self, callback: Callable, *args: Any) -> asyncio.Future:
        """Run function inside executore.

        Return a awaitable object.
        """
        return self.client.loop.run_in_executor(None, callback, *args)

    async def login(
        self, email: str, password: str, *, check_connection: bool = False
    ) -> None:
        """Log a user in."""
        await self.auth.async_login(email, password, check_connection=check_connection)

    async def login_verify_totp(
        self,
        email: str,
        code: str,
        mfa_tokens: dict[str, Any],
        *,
        check_connection: bool = False,
    ) -> None:
        """Verify TOTP code during login."""
        await self.auth.async_login_verify_totp(
            email, code, mfa_tokens, check_connection=check_connection
        )

    async def logout(self) -> None:
        """Close connection and remove all credentials."""
        self.id_token = None
        self.access_token = None
        self.refresh_token = None

        self.started = False
        await self.stop()

        # Cleanup auth data
        if self.user_info_path.exists():
            await self.run_executor(self.user_info_path.unlink)

        await self.client.logout_cleanups()

    async def remove_data(self) -> None:
        """Remove all stored data."""
        if self.started:
            raise ValueError("Cloud not stopped")

        try:
            await self.remote.reset_acme()
        finally:
            await self.run_executor(self._remove_data)

    def _remove_data(self) -> None:
        """Remove all stored data."""
        base_path = self.path()

        # Recursively remove .cloud
        if base_path.is_dir():
            shutil.rmtree(base_path)

        # Guard against .cloud not being a directory
        if base_path.exists():
            base_path.unlink()

    def _write_user_info(self) -> None:
        """Write user info to a file."""
        base_path = self.path()
        if not base_path.exists():
            base_path.mkdir()

        with atomic_write(self.user_info_path, overwrite=True) as fp:
            fp.write(
                json.dumps(
                    {
                        "id_token": self.id_token,
                        "access_token": self.access_token,
                        "refresh_token": self.refresh_token,
                    },
                    indent=4,
                ),
            )
        self.user_info_path.chmod(0o600)

    async def initialize(self) -> None:
        """Initialize the cloud component (load auth and maybe start)."""

        def load_config() -> None | dict[str, Any]:
            """Load config."""
            # Ensure config dir exists
            base_path = self.path()
            if not base_path.exists():
                base_path.mkdir()

            if not self.user_info_path.exists():
                return None

            try:
                content: dict[str, Any] = json.loads(
                    self.user_info_path.read_text(encoding="utf-8"),
                )
            except (ValueError, OSError) as err:
                path = self.user_info_path.relative_to(self.client.base_path)
                self.client.loop.call_soon_threadsafe(
                    self.client.user_message,
                    "load_auth_data",
                    "Home Assistant Cloud error",
                    f"Unable to load authentication from {path}. "
                    "[Please login again](/config/cloud)",
                )
                _LOGGER.warning(
                    "Error loading cloud authentication info from %s: %s",
                    path,
                    err,
                )
                return None

            return content

        info = await self.run_executor(load_config)
        if info is None:
            # No previous token data
            self.started = False
            return

        self.id_token = info["id_token"]
        self.access_token = info["access_token"]
        self.refresh_token = info["refresh_token"]

        self._init_task = asyncio.create_task(self._finish_initialize())

    async def _finish_initialize(self) -> None:
        """Finish initializing the cloud component (load auth and maybe start)."""
        try:
            await self.auth.async_check_token()
        except CloudError:
            _LOGGER.debug("Failed to check cloud token", exc_info=True)

        if await self.async_subscription_is_valid():
            await self._start(skip_subscription_check=True)
            await gather_callbacks(_LOGGER, "on_initialized", self._on_initialized)
            self.started = True

        self._init_task = None

    async def _start(self, skip_subscription_check: bool = False) -> None:
        """Start the cloud component."""
        if skip_subscription_check or await self.async_subscription_is_valid():
            await self.client.cloud_started()
            await gather_callbacks(_LOGGER, "on_start", self._on_start)

    async def stop(self) -> None:
        """Stop the cloud component."""
        if self._init_task:
            self._init_task.cancel()
            self._init_task = None

        await self.client.cloud_stopped()
        await gather_callbacks(_LOGGER, "on_stop", self._on_stop)

    @staticmethod
    def _decode_claims(token: str) -> Mapping[str, Any]:
        """Decode the claims in a token."""
        decoded: Mapping[str, Any] = jwt.decode(
            token,
            options={"verify_signature": False},
        )
        return decoded

    def async_initialize_subscription_reconnection_handler(
        self,
        reason: SubscriptionReconnectionReason,
    ) -> None:
        """Initialize the subscription reconnection handler."""
        if self._subscription_reconnection_task is not None:
            _LOGGER.debug("Subscription reconnection handler already running")
            return

        self._subscription_reconnection_task = asyncio.create_task(
            self._subscription_reconnection_handler(reason),
            name="subscription_reconnection_handler",
        )

    async def async_subscription_is_valid(self) -> bool:
        """Verify that the subscription is valid."""
        if self._subscription_reconnection_task is not None:
            return False

        if self.subscription_expired:
            self.async_initialize_subscription_reconnection_handler(
                SubscriptionReconnectionReason.SUBSCRIPTION_EXPIRED
            )
            return False

        billing_plan_type: str | None = None

        try:
            async with asyncio.timeout(30):
                subscription = await self.payments.subscription_info(skip_renew=True)
            billing_plan_type = subscription.get("billing_plan_type")
        except (CloudApiError, TimeoutError) as err:
            _LOGGER.debug("Subscription validation failed - %s", err)
            self.async_initialize_subscription_reconnection_handler(
                SubscriptionReconnectionReason.CONNECTION_ERROR
            )
            return False
        except NabuCasaBaseError as err:
            _LOGGER.debug(err, exc_info=err)

        if billing_plan_type is None or billing_plan_type == "no_subscription":
            _LOGGER.info("No subscription found")
            self.async_initialize_subscription_reconnection_handler(
                SubscriptionReconnectionReason.NO_SUBSCRIPTION
            )
            return False
        return True

    async def _subscription_reconnection_handler(
        self, reason: SubscriptionReconnectionReason
    ) -> None:
        """Handle subscription reconnection."""
        issue_identifier = f"{reason.value}_{self.expiration_date}"
        while True:
            now_as_utc = utcnow()
            sub_expired = self.expiration_date

            if reason == SubscriptionReconnectionReason.CONNECTION_ERROR:
                self._connection_retry_count += 1
                base_wait = 0.01 + (
                    self._connection_retry_count * random.uniform(0.01, 0.09)
                )
                wait_hours = min(base_wait, 1.0)
            elif sub_expired > (now_as_utc - timedelta(days=1)):
                wait_hours = 3
            elif sub_expired > (now_as_utc - timedelta(days=7)):
                wait_hours = 12
            elif sub_expired > (now_as_utc - timedelta(days=180)):
                wait_hours = 24
            elif sub_expired > (now_as_utc - timedelta(days=400)):
                wait_hours = 96
            else:
                _LOGGER.info(
                    "Subscription expired at %s, not waiting for activation",
                    sub_expired.strftime("%Y-%m-%d"),
                )
                break

            if reason == SubscriptionReconnectionReason.CONNECTION_ERROR:
                _LOGGER.info(
                    "Could not establish connection (attempt %s), "
                    "waiting %s minutes before retrying",
                    self._connection_retry_count,
                    round(wait_hours * 60, 1),
                )
                await self.client.async_create_repair_issue(
                    identifier=issue_identifier,
                    translation_key=reason.value,
                    severity="warning",
                )
            else:
                _LOGGER.info(
                    "Subscription expired at %s, waiting %s hours for activation",
                    sub_expired.strftime("%Y-%m-%d"),
                    wait_hours,
                )
                await self.client.async_create_repair_issue(
                    identifier=issue_identifier,
                    translation_key=reason.value,
                    placeholders={"account_url": ACCOUNT_URL},
                    severity="error",
                )

            await asyncio.sleep(wait_hours * 60 * 60)

            if not self.is_logged_in:
                _LOGGER.info("No longer logged in, stopping reconnection handler")
                break

            try:
                await self.auth.async_renew_access_token()
            except CloudError as err:
                _LOGGER.debug("Could not renew access token (%s)", err)
                continue

            if not self.subscription_expired:
                await self.initialize()
                break

        await self.client.async_delete_repair_issue(identifier=issue_identifier)
        _LOGGER.debug("Stopping subscription reconnection handler")
        self._subscription_reconnection_task = None
        self._connection_retry_count = 0
