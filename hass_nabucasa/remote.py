"""Manage remote UI connections."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta
from enum import Enum
import logging
import random
from ssl import CERT_REQUIRED, SSLContext, SSLError
from typing import TYPE_CHECKING, TypedDict

import aiohttp
import attr
from snitun.exceptions import SniTunConnectionError
from snitun.utils import DEFAULT_PROTOCOL_VERSION
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
from .instance_api import InstanceApiError, PingResult

if TYPE_CHECKING:
    from pathlib import Path

    from . import Cloud, _ClientT


_LOGGER = logging.getLogger(__name__)

# Share of the cert lifetime after which to renew (when not using ARI)
RENEW_AFTER_LIFETIME_RATIO = 2 / 3
# When to escalate renewal problems (share of renewal window with a minimum)
RENEWAL_GRACE_RATIO = 0.3
RENEWAL_ESCALATION_MIN_DAYS = 7
STOP_TIMEOUT = 10

REPAIR_CLIENT_CERTIFICATE_ERROR = "remote_client_certificate_error"

is_cloud_request = ContextVar("IS_CLOUD_REQUEST", default=False)


def default_renewal_time(not_before: datetime, expire_date: datetime) -> datetime:
    """Return when to renew a certificate based on its lifetime."""
    return not_before + (expire_date - not_before) * RENEW_AFTER_LIFETIME_RATIO


def renewal_escalation_time(renewal_time: datetime, expire_date: datetime) -> datetime:
    """Return when failed renewals should be escalated to the user.

    Escalate once part of the time between renewal and expiry has passed, but
    always at least a minimum number of days before expiry.
    """
    return min(
        renewal_time + (expire_date - renewal_time) * RENEWAL_GRACE_RATIO,
        expire_date - timedelta(days=RENEWAL_ESCALATION_MIN_DAYS),
    )


class CertificateRenewalStatus(Enum):
    """Whether the certificate needs to be renewed."""

    VALID = "valid"
    """No renewal needed yet."""

    PENDING_RENEWAL = "pending_renewal"
    """Renewal is due, but failures are not escalated to the user yet."""

    RENEWAL_OVERDUE = "renewal_overdue"
    """Renewal is due and failures should be escalated to the user."""


class RemoteError(Exception):
    """General remote error."""


class RemoteBackendError(RemoteError):
    """Backend problem with nabucasa API."""


class RemoteCertificateError(RemoteError):
    """Raise if no usable certificate could be prepared."""


class RemoteInsecureVersion(RemoteError):
    """Raise if you try to connect with an insecure Core version."""


class RemoteForbidden(RemoteError):
    """Raise if remote connection is not allowed."""


class RemoteNotConnected(RemoteError):
    """Raise if a request need connection and we are not ready."""


class SubscriptionExpired(RemoteError):
    """Raise if we cannot connect because subscription expired."""


class RemoteClientCertificateError(RemoteError):
    """Raise if the client certificate authority can't be loaded."""


def _load_context_certificates(
    context: SSLContext,
    certfile: Path,
    keyfile: Path,
    ca_file: str | None,
) -> None:
    """Load the server certificate and the client certificate authority, if any."""
    context.load_cert_chain(certfile, keyfile)

    if ca_file:
        try:
            context.load_verify_locations(ca_file)
        except (OSError, SSLError) as err:
            raise RemoteClientCertificateError(
                f"Can't load client certificate authority {ca_file}: {err}"
            ) from err
        context.verify_mode = CERT_REQUIRED


class RemoteLatencyLocationResult(TypedDict):
    """Latency results for a location."""

    avg: float | None


@attr.s
class SniTunToken:
    """Handle snitun token."""

    fernet = attr.ib(type=bytes)
    aes_key = attr.ib(type=bytes)
    aes_iv = attr.ib(type=bytes)
    valid = attr.ib(type=datetime)
    throttling = attr.ib(type=int)
    protocol_version = attr.ib(type=int, default=DEFAULT_PROTOCOL_VERSION)


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

        self._results_by_location: dict[str, RemoteLatencyLocationResult] = {}
        self._ping_privileged: bool | None = None

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

        acme_task = self._acme_task
        self._acme_task = None
        acme_task.cancel()
        # Wait for the loop to close the backend, so a following start can't race it
        _, pending = await asyncio.wait([acme_task], timeout=STOP_TIMEOUT)
        if pending:
            _LOGGER.warning("Timeout waiting for the Remote UI loop to stop")

    @property
    def snitun_server(self) -> str | None:
        """Return connected snitun server."""
        return self._snitun_server

    @property
    def certificate_status(self) -> CertificateStatus | None:
        """Return the certificate status."""
        return self._certificate_status

    @property
    def latency_by_location(self) -> dict[str, RemoteLatencyLocationResult]:
        """Return latency results by location."""
        return self._results_by_location

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
            _load_context_certificates,
            context,
            self._acme.path_fullchain,
            self._acme.path_private_key,
            self.cloud.client.remote_ssl_peer_certificate,
        )

        return context

    async def _recreate_backend(self) -> bool:
        """There was a connection error, recreate the backend.

        Return True if the backend was loaded again.
        """
        _LOGGER.info("Recreating backend")
        await self.close_backend()
        # Wait until backend is cleaned
        await asyncio.sleep(5)
        try:
            return await self.load_backend()
        except RemoteCertificateError as err:
            _LOGGER.debug("Unable to prepare a certificate for the backend: %s", err)
            return False

    def _generate_acme_handler(
        self,
        *,
        domain: str,
        aliases: list[str],
        email: str,
    ) -> AcmeHandler:
        """Generate a new ACME handler."""
        return AcmeHandler(
            self.cloud,
            domain,
            aliases,
            email,
            status_callback=self._update_certificate_status,
        )

    async def _recreate_acme(self, domain: str, aliases: list[str], email: str) -> None:
        """Recreate the acme client."""
        if self._acme:
            await self._acme.reset_acme()
        self._acme = self._generate_acme_handler(
            domain=domain, aliases=aliases, email=email
        )

    async def _fetch_ping_results(self) -> list[PingResult] | None:
        """Fetch ping targets and measure latency.

        Returns ping results or None if ping should be skipped or fails.
        """
        try:
            async with asyncio.timeout(30):
                ping_data = await self.cloud.instance.ping_targets()
        except (TimeoutError, InstanceApiError) as err:
            _LOGGER.warning("Unable to fetch ping targets: %s", err)
            return None

        if not (targets := ping_data.get("targets")):
            _LOGGER.debug("No ping targets returned, skipping ping")
            return None
        target_by_ip = {target["ip"]: target for target in targets}

        # The API returns timeout in milliseconds, but we need seconds.
        timeout_seconds = ping_data["timeout"] / 1000
        try:
            if self._ping_privileged is None:
                self._ping_privileged = await utils.async_resolve_ping_privileges(
                    privileged=self.cloud.privileged_ping,
                )
            latency_results = await utils.async_check_latency(
                list(target_by_ip),
                count=ping_data["count"],
                ping_timeout=timeout_seconds,
                privileged=self._ping_privileged,
            )
        except utils.CheckLatencyError as err:
            _LOGGER.warning("Ping latency check failed: %s", err)
            return None

        self._results_by_location = {
            target_by_ip[result["address"]]["location"]: RemoteLatencyLocationResult(
                avg=result["avg_rtt"] if result["is_alive"] else None
            )
            for result in latency_results
        }
        _LOGGER.debug("Latency results by location: %s", self._results_by_location)

        return [
            PingResult(
                ip=result["address"],
                avg=result["avg_rtt"],
                max=result["max_rtt"],
                min=result["min_rtt"],
                reachable=result["is_alive"],
            )
            for result in latency_results
        ]

    async def load_backend(self) -> bool:
        """Load backend details.

        Raise RemoteCertificateError if no usable certificate is available.
        Raise RemoteClientCertificateError if the client certificate authority
        can't be loaded.
        """
        ping_result = await self._fetch_ping_results()

        try:
            async with asyncio.timeout(30):
                data = await self.cloud.instance.register(ping_result=ping_result)
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

        aliases: list[str] = [*self._alias]

        await self._prepare_certificate(instance_domain, aliases, email)
        return await self._start_tunnel()

    async def _prepare_certificate(
        self, instance_domain: str, aliases: list[str], email: str
    ) -> None:
        """Load the certificate and issue a new one if there is no valid one.

        A valid certificate that is due for renewal is kept, so the tunnel can
        start with it, and renewed by the certificate handler loop.
        """
        # Set instance details for certificate
        self._acme = self._generate_acme_handler(
            domain=instance_domain,
            aliases=aliases,
            email=email,
        )

        # Load exists certificate
        self._update_certificate_status(CertificateStatus.LOADING)
        await self._acme.load_certificate()

        # Domain changed / revoke CA
        ca_domains = set(self._acme.alternative_names or [])
        if self._acme.common_name:
            ca_domains.add(self._acme.common_name)
        # The wildcard is only added to new orders, its absence must not force one
        ca_domains.discard(f"*.{instance_domain}")

        if not self._acme.certificate_available or (
            ca_domains and ca_domains != {instance_domain, *aliases}
        ):
            for alias in self.alias or []:
                if not await self._custom_domain_dns_configuration_is_valid(
                    instance_domain, alias
                ):
                    aliases.remove(alias)

        if ca_domains != {instance_domain, *aliases}:
            if ca_domains:
                _LOGGER.warning(
                    "Invalid certificate found for: (%s)",
                    ",".join(ca_domains),
                )
            await self._recreate_acme(instance_domain, aliases, email)

        self._info_loaded.set()

        await self._certificate_renewal_status(use_ari=False)

        if not self._acme.is_valid_certificate:
            try:
                self._update_certificate_status(CertificateStatus.INITIAL_GENERATING)
                await self._acme.issue_certificate()
            except (AcmeJWSVerificationError, AcmeClientError) as err:
                if isinstance(err, AcmeJWSVerificationError):
                    await self._recreate_acme(instance_domain, aliases, email)
                else:
                    _LOGGER.warning(
                        "Failed to issue certificate for %s: %s",
                        ",".join(self._acme.domains),
                        err,
                    )
                self.cloud.client.user_message(
                    "cloud_remote_acme",
                    "Home Assistant Cloud",
                    const.MESSAGE_REMOTE_SETUP,
                )
                self._update_certificate_status(CertificateStatus.INITIAL_CERT_ERROR)
                raise RemoteCertificateError(str(err)) from err

            self.cloud.client.user_message(
                "cloud_remote_acme",
                "Home Assistant Cloud",
                const.MESSAGE_REMOTE_READY,
            )

        self._update_certificate_status(CertificateStatus.INITIAL_LOADED)
        await self._acme.hardening_files()
        self._update_certificate_status(CertificateStatus.READY)

    async def _start_tunnel(self) -> bool:
        """Start the SniTun tunnel with the current certificate."""
        if TYPE_CHECKING:
            assert self._acme is not None

        if self.cloud.client.aiohttp_runner is None:
            _LOGGER.debug("Waiting for aiohttp runner to come available")

            # aiohttp_runner comes available when Home Assistant has started.
            while self.cloud.client.aiohttp_runner is None:  # noqa: ASYNC110
                await asyncio.sleep(1)

        try:
            context = await self._create_context()
        except RemoteClientCertificateError:
            self._update_certificate_status(CertificateStatus.SSL_CLIENT_CONTEXT_ERROR)
            await self.cloud.client.async_create_repair_issue(
                identifier=REPAIR_CLIENT_CERTIFICATE_ERROR,
                translation_key=REPAIR_CLIENT_CERTIFICATE_ERROR,
                placeholders={
                    "ca_file": str(self.cloud.client.remote_ssl_peer_certificate)
                },
                severity="error",
            )
            raise
        except (SSLError, FileNotFoundError) as err:
            should_reset = isinstance(err, FileNotFoundError) or (
                err.reason == "KEY_VALUES_MISMATCH"
            )
            if should_reset:
                self.cloud.client.user_message(
                    "cloud_remote_acme",
                    "Home Assistant Cloud",
                    const.MESSAGE_LOAD_CERTIFICATE_FAILURE,
                )
                await self._recreate_acme(
                    self._acme.domain, self._acme.aliases, self._acme.email
                )
            self._update_certificate_status(CertificateStatus.SSL_CONTEXT_ERROR)
            return False

        await self.cloud.client.async_delete_repair_issue(
            identifier=REPAIR_CLIENT_CERTIFICATE_ERROR
        )

        # Setup snitun / aiohttp wrapper
        _LOGGER.debug("Initializing SniTun")
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

        # Cleanup before stopping, in case stopping snitun times out RemoteUI.stop()
        snitun = self._snitun
        self._snitun = None
        self._acme = None
        self._token = None
        self._instance_domain = None
        self._alias = None
        self._snitun_server = None

        self.cloud.client.dispatcher_message(const.DISPATCH_REMOTE_BACKEND_DOWN)

        # Disconnect snitun
        if snitun:
            await snitun.stop()

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
            async with asyncio.timeout(30):
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
            data.get("protocol_version", DEFAULT_PROTOCOL_VERSION),
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
            async with asyncio.timeout(30):
                await self._refresh_snitun_token()

            # We can not get here without this being set, but mypy does not know that.
            assert self._token is not None

            _LOGGER.debug("Attempting connection to %s", self._snitun_server)
            # snitun.connect spawns the multiplexer task, which spawns a task per
            # connection. Those tasks inherit this context, so handlers see the flag.
            with is_cloud_request.set(True):
                async with asyncio.timeout(30):
                    await self._snitun.connect(
                        self._token.fernet,
                        self._token.aes_key,
                        self._token.aes_iv,
                        throttling=self._token.throttling,
                        protocol_version=self._token.protocol_version,
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
        certificate_backoff = utils.Backoff(
            initial=const.FIVE_MINUTES_IN_SECONDS,
            maximum=6 * const.ONE_HOUR_IN_SECONDS,
            multiplier=2,
        )
        while True:
            try:
                if self._snitun:
                    _LOGGER.debug("Sleeping until tomorrow")
                    await asyncio.sleep(utils.next_midnight() + random.randint(1, 3600))

                else:
                    _LOGGER.debug("Initializing backend")
                    try:
                        loaded = await self.load_backend()
                    except RemoteCertificateError as err:
                        # Certificate issue error, retry with backoffs
                        interval = certificate_backoff.time_to_next_attempt()
                        _LOGGER.debug(
                            "Unable to prepare certificate, trying again in %s: %s",
                            utils.seconds_as_dhms(interval),
                            err,
                        )
                        await asyncio.sleep(interval)
                        continue

                    if loaded:
                        certificate_backoff.reset()
                    else:
                        # Registration or tunnel error, retry every 10 seconds
                        await asyncio.sleep(10)
                        continue

                    if await self._renewal_time(use_ari=False) > utils.utcnow():
                        continue
                    _LOGGER.debug("Certificate is due for renewal after loading")

                if TYPE_CHECKING:
                    assert self._acme is not None

                # Renew certificate?
                renewal_status = await self._certificate_renewal_status()
                if renewal_status is CertificateRenewalStatus.VALID:
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
                    if await self._recreate_backend():
                        self._update_certificate_status(CertificateStatus.READY)
                except AcmeJWSVerificationError as err:
                    _LOGGER.warning(
                        "Renewal of ACME certificate failed, recreating account: %s",
                        err,
                    )
                    self._update_certificate_status(CertificateStatus.RENEWAL_FAILED)
                    await self._recreate_acme(
                        self._acme.domain, self._acme.aliases, self._acme.email
                    )
                    await self._recreate_backend()
                except AcmeClientError as err:
                    meth = (
                        _LOGGER.warning
                        if renewal_status is CertificateRenewalStatus.RENEWAL_OVERDUE
                        else _LOGGER.debug
                    )

                    self._update_certificate_status(CertificateStatus.RENEWAL_FAILED)

                    meth(
                        "Renewal of ACME certificate failed. Trying again later: %s",
                        err,
                    )

            except asyncio.CancelledError:
                break

            except RemoteClientCertificateError as err:
                # Retrying can't help until the client CA configuration changes,
                # and applying a change restarts the remote loop
                _LOGGER.error("Unable to start Remote UI: %s", err)
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
        except TimeoutError, aiohttp.ClientError, AccountsApiError:
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

    async def _renewal_time(self, *, use_ari: bool) -> datetime:
        """Return when the certificate should be renewed.

        Prefer the renewal window suggested by the ACME server, if use_ari is set,
        and fall back to a share of the certificate lifetime, similar to certbot.
        Never renew later than the minimum escalation days before expiry.
        """
        if TYPE_CHECKING:
            assert self._acme is not None
            assert self._acme.expire_date is not None
            assert self._acme.not_before is not None

        latest = self._acme.expire_date - timedelta(days=RENEWAL_ESCALATION_MIN_DAYS)

        if use_ari:
            try:
                if renewal_time := await self._acme.suggested_renewal_time():
                    return min(renewal_time, latest)
            except AcmeClientError as err:
                _LOGGER.debug("Unable to fetch ACME renewal info: %s", err)

        return min(
            default_renewal_time(self._acme.not_before, self._acme.expire_date),
            latest,
        )

    async def _certificate_renewal_status(
        self, *, use_ari: bool = True
    ) -> CertificateRenewalStatus:
        """Check whether the certificate should be renewed.

        Set use_ari to False to skip asking the ACME server for its suggested
        renewal time.
        """
        self._update_certificate_status(CertificateStatus.VALIDATING)

        if TYPE_CHECKING:
            assert self._acme is not None
            assert self.instance_domain is not None

        utcnow = utils.utcnow()

        if not self._acme.certificate_available:
            self._update_certificate_status(CertificateStatus.NO_CERTIFICATE)
            return CertificateRenewalStatus.RENEWAL_OVERDUE

        if self._acme.expire_date is None or self._acme.expire_date <= utcnow:
            self._update_certificate_status(CertificateStatus.EXPIRED)
            return CertificateRenewalStatus.RENEWAL_OVERDUE

        renewal_time = await self._renewal_time(use_ari=use_ari)
        if renewal_time > utcnow:
            return CertificateRenewalStatus.VALID

        if utcnow >= renewal_escalation_time(renewal_time, self._acme.expire_date):
            renewal_status = CertificateRenewalStatus.RENEWAL_OVERDUE
        else:
            renewal_status = CertificateRenewalStatus.PENDING_RENEWAL

        self._update_certificate_status(CertificateStatus.EXPIRING_SOON)

        if not self._acme.aliases:
            return renewal_status

        # Check if defined alias is still valid:
        bad_alias = []
        for alias in self._acme.aliases:
            if not await self._custom_domain_dns_configuration_is_valid(
                self.instance_domain,
                alias,
            ):
                bad_alias.append(alias)  # noqa: PERF401

        if not bad_alias:
            # No bad configuration detected
            return renewal_status

        # Domain validation failed for some aliases
        self._update_certificate_status(CertificateStatus.DOMAIN_VALIDATION_FAILED)

        if renewal_status is CertificateRenewalStatus.PENDING_RENEWAL:
            # Give the user time to fix the aliases before dropping them
            await self.cloud.client.async_create_repair_issue(
                identifier=f"warn_bad_custom_domain_configuration_{self._acme.expire_date.timestamp()}",
                translation_key="warn_bad_custom_domain_configuration",
                placeholders={"custom_domains": ",".join(bad_alias)},
                severity="warning",
            )
            return CertificateRenewalStatus.VALID

        # Recreate the acme client with working domains
        await self.cloud.client.async_create_repair_issue(
            identifier=f"reset_bad_custom_domain_configuration_{self._acme.expire_date.timestamp()}",
            translation_key="reset_bad_custom_domain_configuration",
            placeholders={"custom_domains": ",".join(bad_alias)},
            severity="error",
        )

        await self._recreate_acme(
            self._acme.domain,
            [alias for alias in self._acme.aliases if alias not in bad_alias],
            self._acme.email,
        )
        return CertificateRenewalStatus.RENEWAL_OVERDUE

    async def reset_acme(self) -> None:
        """Reset the ACME client."""
        if not self._acme:
            return
        await self._acme.reset_acme()
