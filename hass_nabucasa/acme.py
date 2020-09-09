"""Handle ACME and local certificates."""
import asyncio
from datetime import datetime, timedelta
import logging
from pathlib import Path
from typing import Optional
import urllib

import OpenSSL
from acme import challenges, client, crypto_util, errors, messages
import async_timeout
from atomicwrites import atomic_write
import attr
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import josepy as jose

from . import cloud_api
from .utils import UTC

FILE_ACCOUNT_KEY = "acme_account.pem"
FILE_PRIVATE_KEY = "remote_private.pem"
FILE_FULLCHAIN = "remote_fullchain.pem"
FILE_REGISTRATION = "acme_reg.json"

ACCOUNT_KEY_SIZE = 2048
PRIVATE_KEY_SIZE = 2048
USER_AGENT = "home-assistant-cloud"

_LOGGER = logging.getLogger(__name__)


class AcmeClientError(Exception):
    """Raise if a acme client error raise."""


class AcmeChallengeError(AcmeClientError):
    """Raise if a challenge fails."""


class AcmeNabuCasaError(AcmeClientError):
    """Raise erros on nabucasa API."""


@attr.s
class ChallengeHandler:
    """Handle ACME data over a challenge."""

    challenge = attr.ib(type=messages.ChallengeResource)
    order = attr.ib(type=messages.OrderResource)
    response = attr.ib(type=challenges.ChallengeResponse)
    validation = attr.ib(type=str)


class AcmeHandler:
    """Class handle a local certification."""

    def __init__(self, cloud, domain: str, email: str) -> None:
        """Initialize local ACME Handler."""
        self.cloud = cloud
        self._acme_server: str = cloud.acme_directory_server
        self._account_jwk: Optional[jose.JWKRSA] = None
        self._acme_client: Optional[client.ClientV2] = None
        self._x509: Optional[x509.Certificate] = None

        self._domain: str = domain
        self._email: str = email

    @property
    def path_account_key(self) -> Path:
        """Return path of account key."""
        return Path(self.cloud.path(FILE_ACCOUNT_KEY))

    @property
    def path_private_key(self) -> Path:
        """Return path of private key."""
        return Path(self.cloud.path(FILE_PRIVATE_KEY))

    @property
    def path_fullchain(self) -> Path:
        """Return path of cert fullchain."""
        return Path(self.cloud.path(FILE_FULLCHAIN))

    @property
    def path_registration_info(self) -> Path:
        """Return path of acme client registration file."""
        return Path(self.cloud.path(FILE_REGISTRATION))

    @property
    def certificate_available(self) -> bool:
        """Return True if a certificate is loaded."""
        return self._x509 is not None

    @property
    def is_valid_certificate(self) -> bool:
        """Validate date of a certificate and return True is valid."""
        if not self._x509:
            return False
        return self._x509.not_valid_after > datetime.utcnow()

    @property
    def expire_date(self) -> Optional[datetime]:
        """Return datetime of expire date for certificate."""
        if not self._x509:
            return None
        return self._x509.not_valid_after.replace(tzinfo=UTC)

    @property
    def common_name(self) -> Optional[str]:
        """Return CommonName of certificate."""
        if not self._x509:
            return None
        return self._x509.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value

    @property
    def fingerprint(self) -> Optional[str]:
        """Return SHA1 hex string as fingerprint."""
        if not self._x509:
            return None
        fingerprint = self._x509.fingerprint(hashes.SHA1())
        return fingerprint.hex()

    def _generate_csr(self) -> bytes:
        """Load or create private key."""
        if self.path_private_key.exists():
            _LOGGER.debug("Load private keyfile: %s", self.path_private_key)
            key_pem = self.path_private_key.read_bytes()
        else:
            _LOGGER.debug("create private keyfile: %s", self.path_private_key)
            key = OpenSSL.crypto.PKey()
            key.generate_key(OpenSSL.crypto.TYPE_RSA, PRIVATE_KEY_SIZE)
            key_pem = OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, key)

            self.path_private_key.write_bytes(key_pem)
            self.path_private_key.chmod(0o600)

        return crypto_util.make_csr(key_pem, [self._domain])

    def _load_account_key(self) -> None:
        """Load or create account key."""
        key = None
        if self.path_account_key.exists():
            _LOGGER.debug("Load account keyfile: %s", self.path_account_key)
            pem = self.path_account_key.read_bytes()
            key = serialization.load_pem_private_key(
                pem, password=None, backend=default_backend()
            )

        else:
            _LOGGER.debug("Create new RSA keyfile: %s", self.path_account_key)
            key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=ACCOUNT_KEY_SIZE,
                backend=default_backend(),
            )

            # Store it to file
            pem = key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            self.path_account_key.write_bytes(pem)
            self.path_account_key.chmod(0o600)

        self._account_jwk = jose.JWKRSA(key=jose.ComparableRSAKey(key))

    def _create_client(self) -> None:
        """Create new ACME client."""
        if self.path_registration_info.exists():
            _LOGGER.info("Load exists ACME registration")
            regr = messages.RegistrationResource.json_loads(
                self.path_registration_info.read_text()
            )

            acme_url = urllib.parse.urlparse(self._acme_server)
            regr_url = urllib.parse.urlparse(regr.uri)

            if acme_url[0] != regr_url[0] or acme_url[1] != regr_url[1]:
                _LOGGER.info("Reset new ACME registration")
                self.path_registration_info.unlink()
                self.path_account_key.unlink()

        # Make sure that account key is loaded
        self._load_account_key()

        # Load a exists registration
        if self.path_registration_info.exists():
            try:
                network = client.ClientNetwork(
                    self._account_jwk, account=regr, user_agent=USER_AGENT
                )
                directory = messages.Directory.from_json(
                    network.get(self._acme_server).json()
                )
                self._acme_client = client.ClientV2(directory, net=network)
            except errors.Error as err:
                _LOGGER.error("Can't connect to ACME server: %s", err)
                raise AcmeClientError() from err
            return

        # Create a new registration
        try:
            network = client.ClientNetwork(self._account_jwk, user_agent=USER_AGENT)
            directory = messages.Directory.from_json(
                network.get(self._acme_server).json()
            )
            self._acme_client = client.ClientV2(directory, net=network)
        except errors.Error as err:
            _LOGGER.error("Can't connect to ACME server: %s", err)
            raise AcmeClientError() from err

        try:
            _LOGGER.info(
                "Register a ACME account with TOS: %s",
                self._acme_client.directory.meta.terms_of_service,
            )
            regr = self._acme_client.new_account(
                messages.NewRegistration.from_data(
                    email=self._email, terms_of_service_agreed=True
                )
            )
        except errors.Error as err:
            _LOGGER.error("Can't register to ACME server: %s", err)
            raise AcmeClientError() from err

        # Store registration info
        self.path_registration_info.write_text(regr.json_dumps_pretty())
        self.path_registration_info.chmod(0o600)

    def _start_challenge(self, csr_pem: str) -> ChallengeHandler:
        """Initialize domain challenge and return token."""
        _LOGGER.info("Initialize challenge for a new ACME certificate")
        try:
            order = self._acme_client.new_order(csr_pem)
        except errors.Error as err:
            _LOGGER.error("Can't order a new ACME challenge: %s", err)
            raise AcmeChallengeError() from None

        # Find DNS challenge
        # pylint: disable=not-an-iterable
        dns_challenge = None
        for auth in order.authorizations:
            for challenge in auth.body.challenges:
                if challenge.typ != "dns-01":
                    continue
                dns_challenge = challenge

        try:
            response, validation = dns_challenge.response_and_validation(
                self._account_jwk
            )
        except errors.Error as err:
            _LOGGER.error("Can't validate the new ACME challenge: %s", err)
            raise AcmeChallengeError() from None

        return ChallengeHandler(dns_challenge, order, response, validation)

    def _finish_challenge(self, handler: ChallengeHandler) -> None:
        """Wait until challenge is finished."""
        _LOGGER.info("Finishing challenge for the new ACME certificate")
        try:
            self._acme_client.answer_challenge(handler.challenge, handler.response)
        except errors.Error as err:
            _LOGGER.error("Can't accept ACME challenge: %s", err)
            raise AcmeChallengeError() from err

        # Wait until it's authorize and fetch certification
        deadline = datetime.now() + timedelta(seconds=90)
        try:
            order = self._acme_client.poll_authorizations(handler.order, deadline)
            order = self._acme_client.finalize_order(
                order, deadline, fetch_alternative_chains=True
            )
        except errors.Error as err:
            _LOGGER.error("Wait of ACME challenge fails: %s", err)
            raise AcmeChallengeError() from err

        # Cleanup the old stuff
        if self.path_fullchain.exists():
            _LOGGER.info("Renew old certificate: %s", self.path_fullchain)
            self.path_fullchain.unlink()
        else:
            _LOGGER.info("Create new certificate: %s", self.path_fullchain)

        with atomic_write(self.path_fullchain, overwrite=True) as fp:
            fp.write(order.fullchain_pem)
        self.path_fullchain.chmod(0o600)

    async def load_certificate(self) -> None:
        """Get x509 Cert-Object."""
        if self._x509 or not self.path_fullchain.exists():
            return

        def _load_cert():
            """Load certificate in a thread."""
            return x509.load_pem_x509_certificate(
                self.path_fullchain.read_bytes(), default_backend()
            )

        try:
            self._x509 = await self.cloud.run_executor(_load_cert)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception loading certificate")

    def _revoke_certificate(self) -> None:
        """Revoke certificate."""
        if not self.path_fullchain.exists():
            _LOGGER.warning("Can't revoke not exists certificate")
            return

        fullchain = jose.ComparableX509(
            OpenSSL.crypto.load_certificate(
                OpenSSL.crypto.FILETYPE_PEM, self.path_fullchain.read_bytes()
            )
        )

        _LOGGER.info("Revoke certificate")
        try:
            self._acme_client.revoke(fullchain, 0)
        except errors.ConflictError:
            pass
        except errors.Error as err:
            # Ignore errors where certificate did not exist
            if "No such certificate" not in str(err):
                _LOGGER.error("Can't revoke certificate: %s", err)
                raise AcmeClientError() from None

        self.path_fullchain.unlink()
        self.path_private_key.unlink()

    def _deactivate_account(self) -> None:
        """Deactivate account."""
        if not self.path_registration_info.exists():
            return

        _LOGGER.info("Load exists ACME registration")
        regr = messages.RegistrationResource.json_loads(
            self.path_registration_info.read_text()
        )

        try:
            self._acme_client.deactivate_registration(regr)
        except errors.Error as err:
            _LOGGER.error("Can't deactivate account: %s", err)
            raise AcmeClientError() from err

        self.path_registration_info.unlink()
        self.path_account_key.unlink()

    async def issue_certificate(self) -> None:
        """Create/Update certificate."""
        if not self._acme_client:
            await self.cloud.run_executor(self._create_client)

        # Initialize challenge / new certificate
        csr = await self.cloud.run_executor(self._generate_csr)
        challenge = await self.cloud.run_executor(self._start_challenge, csr)

        # Update DNS
        try:
            async with async_timeout.timeout(30):
                resp = await cloud_api.async_remote_challenge_txt(
                    self.cloud, challenge.validation
                )
            assert resp.status == 200
        except (asyncio.TimeoutError, AssertionError):
            _LOGGER.error("Can't set challenge token to NabuCasa DNS!")
            raise AcmeNabuCasaError() from None

        # Finish validation
        try:
            _LOGGER.info("Wait 60sec for publishing DNS to ACME provider")
            await asyncio.sleep(60)
            await self.cloud.run_executor(self._finish_challenge, challenge)
            await self.load_certificate()
        finally:
            try:
                async with async_timeout.timeout(30):
                    await cloud_api.async_remote_challenge_cleanup(
                        self.cloud, challenge.validation
                    )
            except asyncio.TimeoutError:
                _LOGGER.error("Failed to clean up challenge from NabuCasa DNS!")

    async def reset_acme(self) -> None:
        """Revoke and deactivate acme certificate/account."""
        _LOGGER.info("Revoke and deactivate ACME user/certificate")
        if not self._acme_client:
            await self.cloud.run_executor(self._create_client)

        try:
            await self.cloud.run_executor(self._revoke_certificate)
            await self.cloud.run_executor(self._deactivate_account)
        finally:
            self._acme_client = None
            self._account_jwk = None
            self._x509 = None

    async def hardening_files(self) -> None:
        """Control permission on files."""

        def _control():
            # Set file permission to 0600
            if self.path_account_key.exists():
                self.path_account_key.chmod(0o600)
            if self.path_registration_info.exists():
                self.path_registration_info.chmod(0o600)
            if self.path_fullchain.exists():
                self.path_fullchain.chmod(0o600)
            if self.path_private_key.exists():
                self.path_private_key.chmod(0o600)

        try:
            await self.cloud.run_executor(_control)
        except OSError:
            _LOGGER.warning("Can't check and hardening file permission")
