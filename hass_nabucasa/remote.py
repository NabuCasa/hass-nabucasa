"""Manage remote UI connections."""
import asyncio
from datetime import datetime, timedelta
import logging
import random
import ssl
from typing import Optional

import aiohttp
import async_timeout
import attr
from snitun.exceptions import SniTunConnectionError
from snitun.utils.aes import generate_aes_keyset
from snitun.utils.aiohttp_client import SniTunClientAioHttp

from . import cloud_api, utils, const
from .acme import AcmeClientError, AcmeHandler

_LOGGER = logging.getLogger(__name__)

RENEW_IF_EXPIRES_DAYS = 25
WARN_RENEW_FAILED_DAYS = 18


class RemoteError(Exception):
    """General remote error."""


class RemoteBackendError(RemoteError):
    """Backend problem with nabucasa API."""


class RemoteInsecureVersion(RemoteError):
    """Raise if you try to connect with an insecure Core version."""


class RemoteNotConnected(RemoteError):
    """Raise if a request need connection and we are not ready."""


class SubscriptionExpired(RemoteError):
    """Raise if we cannot connect because subscription expired."""


@attr.s
class SniTunToken:
    """Handle snitun token."""

    fernet = attr.ib(type=bytes)
    aes_key = attr.ib(type=bytes)
    aes_iv = attr.ib(type=bytes)
    valid = attr.ib(type=datetime)
    throttling = attr.ib(type=int)


@attr.s
class Certificate:
    """Handle certificate details."""

    common_name = attr.ib(type=str)
    expire_date = attr.ib(type=datetime)
    fingerprint = attr.ib(type=str)


class RemoteUI:
    """Class to help manage remote connections."""

    def __init__(self, cloud):
        """Initialize cloudhooks."""
        self.cloud = cloud
        self._acme = None
        self._snitun = None
        self._snitun_server = None
        self._instance_domain = None
        self._reconnect_task = None
        self._acme_task = None
        self._token = None

        self._info_loaded = asyncio.Event()

        # Register start/stop
        cloud.register_on_start(self.start)
        cloud.register_on_stop(self.stop)

    async def start(self) -> None:
        """Start remote UI loop."""
        self._acme_task = self.cloud.run_task(self._certificate_handler())
        await self._info_loaded.wait()

    async def stop(self) -> None:
        """Stop remote UI loop."""
        self._acme_task.cancel()
        self._acme_task = None

    @property
    def snitun_server(self) -> Optional[str]:
        """Return connected snitun server."""
        return self._snitun_server

    @property
    def instance_domain(self) -> Optional[str]:
        """Return instance domain."""
        return self._instance_domain

    @property
    def is_connected(self) -> bool:
        """Return true if we are ready to connect."""
        return False if self._snitun is None else self._snitun.is_connected

    @property
    def certificate(self) -> Optional[Certificate]:
        """Return certificate details."""
        if not self._acme or not self._acme.certificate_available:
            return None

        return Certificate(
            self._acme.common_name, self._acme.expire_date, self._acme.fingerprint
        )

    async def _create_context(self) -> ssl.SSLContext:
        """Create SSL context with acme certificate."""
        context = utils.server_context_modern()

        await self.cloud.run_executor(
            context.load_cert_chain,
            self._acme.path_fullchain,
            self._acme.path_private_key,
        )

        return context

    async def load_backend(self) -> bool:
        """Load backend details."""
        # Load instance data from backend
        try:
            async with async_timeout.timeout(30):
                resp = await cloud_api.async_remote_register(self.cloud)
            resp.raise_for_status()
        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            msg = "Can't update remote details from Home Assistant cloud"
            if isinstance(err, aiohttp.ClientResponseError):
                msg += f" ({err.status})"  # pylint: disable=no-member
            elif isinstance(err, asyncio.TimeoutError):
                msg += " (timeout)"
            _LOGGER.error(msg)
            return False
        data = await resp.json()

        # Extract data
        _LOGGER.debug("Retrieve instance data: %s", data)
        domain = data["domain"]
        email = data["email"]
        server = data["server"]

        # Cache data
        self._instance_domain = domain
        self._snitun_server = server

        # Set instance details for certificate
        self._acme = AcmeHandler(self.cloud, domain, email)

        # Load exists certificate
        await self._acme.load_certificate()

        # Domain changed / revoke CA
        ca_domain = self._acme.common_name
        if ca_domain and ca_domain != domain:
            _LOGGER.warning("Invalid certificate found: %s", ca_domain)
            await self._acme.reset_acme()

        self._info_loaded.set()

        should_create_cert = not self._acme.certificate_available

        if should_create_cert or self._acme.expire_date < utils.utcnow() + timedelta(
            days=RENEW_IF_EXPIRES_DAYS
        ):
            try:
                await self._acme.issue_certificate()
            except AcmeClientError:
                self.cloud.client.user_message(
                    "cloud_remote_acme",
                    "Home Assistant Cloud",
                    const.MESSAGE_REMOTE_SETUP,
                )
                return
            else:
                if should_create_cert:
                    self.cloud.client.user_message(
                        "cloud_remote_acme",
                        "Home Assistant Cloud",
                        const.MESSAGE_REMOTE_READY,
                    )

        await self._acme.hardening_files()

        if self.cloud.client.aiohttp_runner is None:
            _LOGGER.debug("Waiting for aiohttp runner to come available")

            # aiohttp_runner comes available when Home Assistant has started.
            while self.cloud.client.aiohttp_runner is None:
                await asyncio.sleep(1)

        # Setup snitun / aiohttp wrapper
        _LOGGER.debug("Initializing SniTun")
        context = await self._create_context()
        self._snitun = SniTunClientAioHttp(
            self.cloud.client.aiohttp_runner,
            context,
            snitun_server=self._snitun_server,
            snitun_port=443,
        )

        _LOGGER.debug("Starting SniTun")
        await self._snitun.start()
        self.cloud.client.dispatcher_message(const.DISPATCH_REMOTE_BACKEND_UP)

        _LOGGER.debug(
            "Connecting remote backend: %s", self.cloud.client.remote_autostart
        )
        # Connect to remote is autostart enabled
        if self.cloud.client.remote_autostart:
            self.cloud.run_task(self.connect())

        return True

    async def close_backend(self) -> None:
        """Close connections and shutdown backend."""
        _LOGGER.debug("Closing backend")

        # Close reconnect task
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        # Disconnect snitun
        if self._snitun:
            await self._snitun.stop()

        # Cleanup
        self._snitun = None
        self._acme = None
        self._token = None
        self._instance_domain = None
        self._snitun_server = None

        self.cloud.client.dispatcher_message(const.DISPATCH_REMOTE_BACKEND_DOWN)

    async def handle_connection_requests(self, caller_ip: str) -> None:
        """Handle connection requests."""
        if not self._snitun:
            _LOGGER.error("Can't handle request-connection without backend")
            raise RemoteNotConnected()

        if self._snitun.is_connected:
            return
        await self.connect()

    async def _refresh_snitun_token(self) -> None:
        """Handle snitun token."""
        if self._token and self._token.valid > utils.utcnow():
            _LOGGER.debug("Don't need refresh snitun token")
            return

        if self.cloud.subscription_expired:
            raise SubscriptionExpired()

        # Generate session token
        aes_key, aes_iv = generate_aes_keyset()
        try:
            async with async_timeout.timeout(30):
                resp = await cloud_api.async_remote_token(self.cloud, aes_key, aes_iv)
                if resp.status == 409:
                    raise RemoteInsecureVersion()
                if resp.status != 200:
                    raise RemoteBackendError()
        except (asyncio.TimeoutError, aiohttp.ClientError):
            raise RemoteBackendError() from None

        data = await resp.json()
        self._token = SniTunToken(
            data["token"].encode(),
            aes_key,
            aes_iv,
            utils.utc_from_timestamp(data["valid"]),
            data["throttling"],
        )

    async def connect(self) -> None:
        """Connect to snitun server."""
        if not self._snitun:
            _LOGGER.error("Can't handle request-connection without backend")
            raise RemoteNotConnected()

        # Check if we already connected
        if self._snitun.is_connected:
            return

        insecure = False
        try:
            await self._refresh_snitun_token()
            await self._snitun.connect(
                self._token.fernet,
                self._token.aes_key,
                self._token.aes_iv,
                throttling=self._token.throttling,
            )

            self.cloud.client.dispatcher_message(const.DISPATCH_REMOTE_CONNECT)
        except SniTunConnectionError:
            _LOGGER.error("Connection problem to snitun server")
        except RemoteBackendError:
            _LOGGER.error("Can't refresh the snitun token")
        except RemoteInsecureVersion:
            self.cloud.client.user_message(
                "connect_remote_insecure",
                "Home Assistant Cloud error",
                "Remote connection is disabled because this Home Assistant instance is marked as insecure. For more information and to enable it again, visit the [Nabu Casa Account page](https://account.nabucasa.com).",
            )
            insecure = True
        except SubscriptionExpired:
            pass
        except AttributeError:
            pass  # Ignore because HA shutdown on snitun token refresh
        finally:
            # start retry task
            if self._snitun and not self._reconnect_task and not insecure:
                self._reconnect_task = self.cloud.run_task(self._reconnect_snitun())

            # Disconnect if the instance is mark as insecure and we're in reconnect mode
            elif self._reconnect_task and insecure:
                self.cloud.run_task(self.disconnect())

    async def disconnect(self, clear_snitun_token=False) -> None:
        """Disconnect from snitun server."""
        if not self._snitun:
            _LOGGER.error("Can't handle request-connection without backend")
            raise RemoteNotConnected()

        # Stop reconnect task
        if self._reconnect_task:
            self._reconnect_task.cancel()

        if clear_snitun_token:
            self._token = None

        # Check if we already connected
        if not self._snitun.is_connected:
            return
        await self._snitun.disconnect()
        self.cloud.client.dispatcher_message(const.DISPATCH_REMOTE_DISCONNECT)

    async def _reconnect_snitun(self) -> None:
        """Reconnect after disconnect."""
        try:
            while True:
                if self._snitun.is_connected:
                    await self._snitun.wait()

                self.cloud.client.dispatcher_message(const.DISPATCH_REMOTE_DISCONNECT)
                await asyncio.sleep(random.randint(1, 15))
                await self.connect()
        except asyncio.CancelledError:
            pass
        finally:
            _LOGGER.debug("Close remote UI reconnect guard")
            self._reconnect_task = None

    async def _certificate_handler(self) -> None:
        """Handle certification ACME Tasks."""
        while True:
            try:
                if self._snitun:
                    _LOGGER.debug("Sleeping until tomorrow")
                    await asyncio.sleep(utils.next_midnight() + random.randint(1, 3600))

                else:
                    _LOGGER.debug("Initializing backend")
                    if not await self.load_backend():
                        await asyncio.sleep(10)
                    continue

                # Renew certificate?
                if self._acme.expire_date > utils.utcnow() + timedelta(
                    days=RENEW_IF_EXPIRES_DAYS
                ):
                    continue

                # Renew certificate
                try:
                    _LOGGER.debug("Renewing certificate")
                    await self._acme.issue_certificate()
                    await self.close_backend()

                    # Wait until backend is cleaned
                    await asyncio.sleep(5)
                    await self.load_backend()
                except AcmeClientError:
                    # Only log as warning if we have a certain amount of days left
                    if (
                        self._acme.expire_date
                        > utils.utcnow()
                        < timedelta(days=WARN_RENEW_FAILED_DAYS)
                    ):
                        meth = _LOGGER.warning
                    else:
                        meth = _LOGGER.debug

                    meth("Renewal of ACME certificate failed. Trying again later")

            except asyncio.CancelledError:
                break

            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected error in Remote UI loop")
                raise

        _LOGGER.debug("Stopping Remote UI loop")
        await self.close_backend()
