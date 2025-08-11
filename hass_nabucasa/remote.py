"""Manage remote UI connections."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta
import logging
import random
from ssl import SSLContext, SSLError
from typing import TYPE_CHECKING

import aiohttp
import async_timeout
import attr
from snitun.exceptions import SniTunConnectionError
from snitun.utils.aes import generate_aes_keyset
from snitun.utils.aiohttp_client import SniTunClientAioHttp

from . import const, utils
from .accounts_api import AccountsApiError
from .acme import AcmeClientError, AcmeHandler, AcmeJWSVerificationError
from .const import (
    DISPATCH_CERTIFICATE_STATUS,
    CertificateStatus,
    SubscriptionReconnectionReason,
)
from .instance_api import InstanceApiError

if TYPE_CHECKING:
    from . import Cloud, _ClientT


_LOGGER = logging.getLogger(__name__)

RENEW_IF_EXPIRES_DAYS = 25
WARN_RENEW_FAILED_DAYS = 18

is_cloud_request = ContextVar("IS_CLOUD_REQUEST", default=False)


class RemoteError(Exception):
    """General remote error."""


class RemoteBackendError(RemoteError):
    """Backend problem with nabucasa API."""


class RemoteInsecureVersion(RemoteError):
    """Raise if you try to connect with an insecure Core version."""


class RemoteForbidden(RemoteError):
    """Raise if remote connection is not allowed."""


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
    alternative_names = attr.ib(type=list[str] | None)


class RemoteUI:
    """Class to help manage remote connections."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize cloudhooks."""
        self.cloud = cloud
        self._acme: AcmeHandler | None = None
        self._snitun: SniTunClientAioHttp | None = None
        self._snitun_server: str | None = None
        self._instance_domain: str | None = None
        self._alias: list[str] | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._acme_task: asyncio.Task | None = None
        self._token: SniTunToken | None = None
        self._certificate_status: CertificateStatus | None = None

        self._info_loaded = asyncio.Event()

        # Register start/stop
        cloud.register_on_start(self.start)
        cloud.register_on_stop(self.stop)

    async def start(self) -> None:
        """Start remote UI loop."""
        if self.cloud.subscription_expired:
            self.cloud.async_initialize_subscription_reconnection_handler(
                SubscriptionReconnectionReason.SUBSCRIPTION_EXPIRED,
            )
            return
        self._acme_task = asyncio.create_task(self._certificate_handler())
        await self._info_loaded.wait()

    async def stop(self) -> None:
        """Stop remote UI loop."""
        if self._acme_task is None:
            return

        self._acme_task.cancel()
        self._acme_task = None

    @property
    def snitun_server(self) -> str | None:
        """Return connected snitun server."""
        return self._snitun_server

    @property
    def certificate_status(self) -> CertificateStatus | None:
        """Return the certificate status."""
        return self._certificate_status

    def _update_certificate_status(
        self,
        status: CertificateStatus,
    ) -> None:
        """Update certificate status and notify via dispatcher."""
        if self._certificate_status == status:
            return

        self._certificate_status = status
        _LOGGER.debug("Certificate status: %s", status)
        self.cloud.client.dispatcher_message(DISPATCH_CERTIFICATE_STATUS, status)

    @property
    def instance_domain(self) -> str | None:
        """Return instance domain."""
        return self._instance_domain

    @property
    def alias(self) -> list[str] | None:
        """Return alias."""
        return self._alias

    @property
    def is_connected(self) -> bool:
        """Return true if we are ready to connect."""
        return bool(False if self._snitun is None else self._snitun.is_connected)

    @property
    def certificate(self) -> Certificate | None:
        """Return certificate details."""
        if (
            not self._acme
            or not self._acme.certificate_available
            or self._acme.common_name is None
            or self._acme.expire_date is None
            or self._acme.fingerprint is None
        ):
            return None

        return Certificate(
            self._acme.common_name,
            self._acme.expire_date,
            self._acme.fingerprint,
            alternative_names=self._acme.alternative_names,
        )

    async def _create_context(self) -> SSLContext:
        """Create SSL context with acme certificate."""
        context = utils.server_context_modern()

        # We can not get here without this being set, but mypy does not know that.
        assert self._acme is not None

        await self.cloud.run_executor(
            context.load_cert_chain,
            self._acme.path_fullchain,
            self._acme.path_private_key,
        )

        return context

    async def _recreate_backend(self) -> None:
        """There was a connection error, recreate the backend."""
        _LOGGER.info("Recreating backend")
        await self.close_backend()
        # Wait until backend is cleaned
        await asyncio.sleep(5)
        await self.load_backend()

    def _generate_acme_handler(self, *, domains: list[str], email: str) -> AcmeHandler:
        """Generate a new ACME handler."""
        return AcmeHandler(
            self.cloud,
            domains,
            email,
            status_callback=self._update_certificate_status,
        )

    async def _recreate_acme(self, domains: list[str], email: str) -> None:
        """Recreate the acme client."""
        if self._acme:
            await self._acme.reset_acme()
        self._acme = self._generate_acme_handler(domains=domains, email=email)

    async def load_backend(self) -> bool:
        """Load backend details."""
        try:
            async with async_timeout.timeout(30):
                data = await self.cloud.instance.register()
        except (TimeoutError, InstanceApiError) as err:
            msg = "Can't update remote details from Home Assistant cloud"
            if isinstance(err, TimeoutError):
                msg += " (timeout)"
            else:
                msg += f" ({err})"
            _LOGGER.error(msg)
            return False

        # Extract data
        _LOGGER.debug("Retrieved instance data: %s", data)

        instance_domain = data["domain"]
        email = data["email"]
        server = data["server"]

        # Cache data
        self._instance_domain = instance_domain
        self._snitun_server = server
        self._alias = data.get("alias", [])

        domains: list[str] = [instance_domain, *self._alias]

        # Set instance details for certificate
        self._acme = self._generate_acme_handler(domains=domains, email=email)

        # Load exists certificate
        self._update_certificate_status(CertificateStatus.LOADING)
        await self._acme.load_certificate()

        # Domain changed / revoke CA
        ca_domains = set(self._acme.alternative_names or [])
        if self._acme.common_name:
            ca_domains.add(self._acme.common_name)

        if not self._acme.certificate_available or (
            ca_domains and ca_domains != set(domains)
        ):
            for alias in self.alias or []:
                if not await self._custom_domain_dns_configuration_is_valid(
                    instance_domain, alias
                ):
                    domains.remove(alias)

        if ca_domains != set(domains):
            if ca_domains:
                _LOGGER.warning(
                    "Invalid certificate found for: (%s)",
                    ",".join(ca_domains),
                )
            await self._recreate_acme(domains, email)

        self._info_loaded.set()

        should_create_cert = await self._should_renew_certificates()

        if should_create_cert:
            try:
                self._update_certificate_status(CertificateStatus.INITIAL_GENERATING)
                await self._acme.issue_certificate()
            except (AcmeJWSVerificationError, AcmeClientError) as err:
                if isinstance(err, AcmeJWSVerificationError):
                    await self._recreate_acme(domains, email)
                else:
                    _LOGGER.warning(
                        "Failed to issue certificate for %s: %s", ",".join(domains), err
                    )
                self.cloud.client.user_message(
                    "cloud_remote_acme",
                    "Home Assistant Cloud",
                    const.MESSAGE_REMOTE_SETUP,
                )
                self._update_certificate_status(CertificateStatus.INITIAL_CERT_ERROR)
                return False

            self.cloud.client.user_message(
                "cloud_remote_acme",
                "Home Assistant Cloud",
                const.MESSAGE_REMOTE_READY,
            )

        self._update_certificate_status(CertificateStatus.INITIAL_LOADED)
        await self._acme.hardening_files()
        self._update_certificate_status(CertificateStatus.READY)

        if self.cloud.client.aiohttp_runner is None:
            _LOGGER.debug("Waiting for aiohttp runner to come available")

            # aiohttp_runner comes available when Home Assistant has started.
            while self.cloud.client.aiohttp_runner is None:  # noqa: ASYNC110
                await asyncio.sleep(1)

        try:
            context = await self._create_context()
        except SSLError as err:
            if err.reason == "KEY_VALUES_MISMATCH":
                self.cloud.client.user_message(
                    "cloud_remote_acme",
                    "Home Assistant Cloud",
                    const.MESSAGE_LOAD_CERTIFICATE_FAILURE,
                )
                await self._recreate_acme(domains, email)
            self._update_certificate_status(CertificateStatus.SSL_CONTEXT_ERROR)
            return False

        # Setup snitun / aiohttp wrapper
        _LOGGER.debug("Initializing SniTun")
        self._snitun = SniTunClientAioHttp(
            self.cloud.client.aiohttp_runner,
            context,
            snitun_server=self._snitun_server,
            snitun_port=443,
        )

        _LOGGER.debug("Starting SniTun")
        is_cloud_request.set(True)
        await self._snitun.start(False, self._recreate_backend)
        self.cloud.client.dispatcher_message(const.DISPATCH_REMOTE_BACKEND_UP)

        _LOGGER.debug(
            "Connecting remote backend: %s",
            self.cloud.client.remote_autostart,
        )
        # Connect to remote is autostart enabled
        if self.cloud.client.remote_autostart:
            asyncio.create_task(self.connect())

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
        self._alias = None
        self._snitun_server = None

        self.cloud.client.dispatcher_message(const.DISPATCH_REMOTE_BACKEND_DOWN)

    async def handle_connection_requests(self, caller_ip: str) -> None:  # noqa: ARG002
        """Handle connection requests."""
        if not self._snitun:
            raise RemoteNotConnected("Can't handle request-connection without backend")

        if self._snitun.is_connected:
            return
        await self.connect()

    async def _refresh_snitun_token(self) -> None:
        """Handle snitun token."""
        if self._token and self._token.valid > utils.utcnow():
            _LOGGER.debug("Don't need refresh snitun token")
            return

        if self.cloud.subscription_expired:
            raise SubscriptionExpired

        # Generate session token
        aes_key, aes_iv = generate_aes_keyset()
        try:
            async with async_timeout.timeout(30):
                data = await self.cloud.instance.snitun_token(
                    aes_key=aes_key, aes_iv=aes_iv
                )
        except TimeoutError:
            raise RemoteBackendError from None
        except InstanceApiError as err:
            if err.status == 409:
                raise RemoteInsecureVersion from err
            if err.status == 403:
                raise RemoteForbidden(err.reason or err) from err
            raise RemoteBackendError from None
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
            raise RemoteNotConnected("Can't handle request-connection without backend")

        # Check if we already connected
        if self._snitun.is_connected:
            return

        insecure = False
        forbidden = False
        try:
            _LOGGER.debug("Refresh snitun token")
            async with async_timeout.timeout(30):
                await self._refresh_snitun_token()

            # We can not get here without this being set, but mypy does not know that.
            assert self._token is not None

            _LOGGER.debug("Attempting connection to %s", self._snitun_server)
            async with async_timeout.timeout(30):
                await self._snitun.connect(
                    self._token.fernet,
                    self._token.aes_key,
                    self._token.aes_iv,
                    throttling=self._token.throttling,
                )
            _LOGGER.debug("Connected")

            self.cloud.client.dispatcher_message(const.DISPATCH_REMOTE_CONNECT)
        except TimeoutError:
            _LOGGER.error("Timeout connecting to snitun server")
        except SniTunConnectionError as err:
            _LOGGER.log(
                logging.ERROR if self._reconnect_task is not None else logging.INFO,
                "Connection problem to snitun server (%s)",
                err,
            )
        except RemoteBackendError:
            _LOGGER.error("Can't refresh the snitun token")
        except RemoteForbidden as err:
            _LOGGER.error("Remote connection is not allowed %s", err)
            forbidden = True
        except RemoteInsecureVersion:
            self.cloud.client.user_message(
                "connect_remote_insecure",
                "Home Assistant Cloud error",
                "Remote connection is disabled because this Home Assistant instance "
                "is marked as insecure. For more information and to enable it again, "
                "visit the [Nabu Casa Account page](https://account.nabucasa.com).",
            )
            insecure = True
        except SubscriptionExpired:
            pass
        except AttributeError:
            pass  # Ignore because HA shutdown on snitun token refresh
        finally:
            # start retry task
            if (
                self._snitun
                and not self._reconnect_task
                and not (insecure or forbidden)
            ):
                self._reconnect_task = asyncio.create_task(self._reconnect_snitun())

            # Disconnect if the instance is mark as insecure and we're in reconnect mode
            elif self._reconnect_task and (insecure or forbidden):
                asyncio.create_task(self.disconnect())

    async def disconnect(self, clear_snitun_token: bool = False) -> None:
        """Disconnect from snitun server."""
        if not self._snitun:
            raise RemoteNotConnected("Can't handle request-connection without backend")

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
                if self._snitun is not None and self._snitun.is_connected:
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

                if TYPE_CHECKING:
                    assert self._acme is not None

                # Renew certificate?
                if not await self._should_renew_certificates():
                    self._update_certificate_status(CertificateStatus.READY)
                    continue

                # Renew certificate
                try:
                    _LOGGER.debug("Renewing certificate")
                    self._update_certificate_status(
                        CertificateStatus.RENEWAL_GENERATING
                    )
                    await self._acme.issue_certificate()
                    self._update_certificate_status(CertificateStatus.RENEWAL_LOADED)
                    await self._recreate_backend()
                    self._update_certificate_status(CertificateStatus.READY)
                except AcmeClientError as err:
                    # Only log as warning if we have a certain amount of days left
                    if self._acme.expire_date is None or (
                        self._acme.expire_date
                        > utils.utcnow()
                        < (utils.utcnow() + timedelta(days=WARN_RENEW_FAILED_DAYS))
                    ):
                        meth = _LOGGER.warning
                    else:
                        meth = _LOGGER.debug

                    self._update_certificate_status(CertificateStatus.RENEWAL_FAILED)

                    meth(
                        "Renewal of ACME certificate failed. Trying again later: %s",
                        err,
                    )

            except asyncio.CancelledError:
                break

            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected error in Remote UI loop")
                raise

        _LOGGER.debug("Stopping Remote UI loop")
        await self.close_backend()

    async def _check_cname(self, hostname: str) -> list[str]:
        """Get CNAME records for hostname."""
        try:
            return await self.cloud.accounts.instance_resolve_dns_cname(
                hostname=hostname
            )
        except (TimeoutError, aiohttp.ClientError, AccountsApiError):
            _LOGGER.error("Can't resolve CNAME for %s", hostname)
        return []

    async def _custom_domain_dns_configuration_is_valid(
        self,
        instance_domain: str,
        custom_domain: str,
    ) -> bool:
        """Validate custom domain."""
        # Check primary entry
        if instance_domain not in await self._check_cname(custom_domain):
            return False

        # Check LE entry
        return f"_acme-challenge.{instance_domain}" in await self._check_cname(
            f"_acme-challenge.{custom_domain}",
        )

    async def _should_renew_certificates(self) -> bool:
        """Check if certificates should be renewed."""
        self._update_certificate_status(CertificateStatus.VALIDATING)

        if TYPE_CHECKING:
            assert self._acme is not None
            assert self.instance_domain is not None

        if not self._acme.certificate_available:
            self._update_certificate_status(CertificateStatus.NO_CERTIFICATE)
            return True

        utcnow = utils.utcnow()

        if self._acme.expire_date is None or self._acme.expire_date <= utcnow:
            self._update_certificate_status(CertificateStatus.EXPIRED)
            return True

        # Check if certificate is expiring soon
        if self._acme.expire_date > (utcnow + timedelta(days=RENEW_IF_EXPIRES_DAYS)):
            return False

        self._update_certificate_status(CertificateStatus.EXPIRING_SOON)

        check_alias = [
            domain for domain in self._acme.domains if domain != self.instance_domain
        ]

        if not check_alias:
            return True

        # Check if defined alias is still valid:
        bad_alias = []
        for alias in check_alias:
            if not await self._custom_domain_dns_configuration_is_valid(
                self.instance_domain,
                alias,
            ):
                bad_alias.append(alias)  # noqa: PERF401

        if not bad_alias:
            # No bad configuration detected
            return True

        # Domain validation failed for some aliases
        self._update_certificate_status(CertificateStatus.DOMAIN_VALIDATION_FAILED)

        if self._acme.expire_date > (
            utils.utcnow() + timedelta(days=WARN_RENEW_FAILED_DAYS)
        ):
            await self.cloud.client.async_create_repair_issue(
                identifier=f"warn_bad_custom_domain_configuration_{self._acme.expire_date.timestamp()}",
                translation_key="warn_bad_custom_domain_configuration",
                placeholders={"custom_domains": ",".join(bad_alias)},
                severity="warning",
            )
            return False

        # Recreate the acme client with working domains
        await self.cloud.client.async_create_repair_issue(
            identifier=f"reset_bad_custom_domain_configuration_{self._acme.expire_date.timestamp()}",
            translation_key="reset_bad_custom_domain_configuration",
            placeholders={"custom_domains": ",".join(bad_alias)},
            severity="error",
        )

        await self._recreate_acme(
            [domain for domain in self._acme.domains if domain not in bad_alias],
            self._acme.email,
        )
        return True

    async def reset_acme(self) -> None:
        """Reset the ACME client."""
        if not self._acme:
            return
        await self._acme.reset_acme()
