"""Manage remote UI connections."""
import asyncio
from datetime import datetime, timedelta
import logging
import random
import ssl
from typing import Optional

import async_timeout
import attr
from snitun.exceptions import SniTunConnectionError
from snitun.utils.aes import generate_aes_keyset
from snitun.utils.aiohttp_client import SniTunClientAioHttp

from . import cloud_api, utils, const
from .acme import AcmeClientError, AcmeHandler

_LOGGER = logging.getLogger(__name__)


class RemoteError(Exception):
    """General remote error."""


class RemoteBackendError(RemoteError):
    """Backend problem with nabucasa API."""


class RemoteNotConnected(RemoteError):
    """Raise if a request need connection and we are not ready."""


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

        # Register start/stop
        cloud.iot.register_on_connect(self.load_backend)
        cloud.iot.register_on_disconnect(self.close_backend)

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
        if not self._snitun:
            return False
        return self._snitun.is_connected

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
            str(self._acme.path_fullchain),
            str(self._acme.path_private_key),
        )

        return context

    async def load_backend(self) -> None:
        """Load backend details."""
        if self._snitun:
            return

        # Setup background task for ACME certification handler
        if not self._acme_task:
            self._acme_task = self.cloud.run_task(self._certificate_handler())

        # Load instance data from backend
        try:
            async with async_timeout.timeout(15):
                resp = await cloud_api.async_remote_register(self.cloud)
            assert resp.status == 200
        except (asyncio.TimeoutError, AssertionError):
            _LOGGER.error("Can't update remote details from Home Assistant cloud")
            return
        data = await resp.json()

        # Extract data
        _LOGGER.debug("Retrieve instance data: %s", data)
        domain = data["domain"]
        email = data["email"]
        server = data["server"]

        # Set instance details for certificate
        self._acme = AcmeHandler(self.cloud, domain, email)

        # Load exists certificate
        await self._acme.load_certificate()

        # Domain changed / revoke CA
        ca_domain = self._acme.common_name
        if ca_domain is not None and ca_domain != domain:
            _LOGGER.warning("Invalid certificate found: %s", ca_domain)
            await self._acme.reset_acme()

        # Issue a certificate
        if not self._acme.is_valid_certificate:
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
                self.cloud.client.user_message(
                    "cloud_remote_acme",
                    "Home Assistant Cloud",
                    const.MESSAGE_REMOTE_READY,
                )
        await self._acme.hardening_files()

        # Setup snitun / aiohttp wrapper
        context = await self._create_context()
        self._snitun = SniTunClientAioHttp(
            self.cloud.client.aiohttp_runner,
            context,
            snitun_server=server,
            snitun_port=443,
        )

        # Cache data
        self._instance_domain = domain
        self._snitun_server = server

        await self._snitun.start()
        self.cloud.client.dispatcher_message(const.DISPATCH_REMOTE_BACKEND_UP)

        # Connect to remote is autostart enabled
        if self.cloud.client.remote_autostart:
            self.cloud.run_task(self.connect())

    async def close_backend(self) -> None:
        """Close connections and shutdown backend."""
        # Close reconnect task
        if self._reconnect_task:
            self._reconnect_task.cancel()

        # Close ACME certificate handler
        if self._acme_task:
            self._acme_task.cancel()

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

        # Generate session token
        aes_key, aes_iv = generate_aes_keyset()
        try:
            async with async_timeout.timeout(15):
                resp = await cloud_api.async_remote_token(self.cloud, aes_key, aes_iv)
            assert resp.status == 200
        except (asyncio.TimeoutError, AssertionError):
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
        finally:
            # start retry task
            if not self._reconnect_task:
                self._reconnect_task = self.cloud.run_task(self._reconnect_snitun())

    async def disconnect(self) -> None:
        """Disconnect from snitun server."""
        if not self._snitun:
            _LOGGER.error("Can't handle request-connection without backend")
            raise RemoteNotConnected()

        # Stop reconnect task
        if self._reconnect_task:
            self._reconnect_task.cancel()

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
        try:
            while True:
                await asyncio.sleep(utils.next_midnight())

                # Backend not initialize / No certificate issue now
                if not self._snitun:
                    await self.load_backend()
                    continue

                # Renew certificate?
                if self._acme.expire_date > utils.utcnow() + timedelta(days=14):
                    continue

                # Renew certificate
                try:
                    await self._acme.issue_certificate()
                    await self.close_backend()
                    await self.load_backend()
                except AcmeClientError:
                    _LOGGER.warning(
                        "Renew of ACME certificate fails. Try it lager again"
                    )

        except asyncio.CancelledError:
            pass
        finally:
            self._acme_task = None
