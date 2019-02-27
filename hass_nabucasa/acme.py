"""Handle ACME and local certificates."""
import logging
from pathlib import Path
import urllib

import attr
import OpenSSL
from acme import challenges, client, errors, messages, crypto_util
import async_timeout
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import josepy as jose

from . import cloud_api

FILE_ACCOUNT_KEY = "acme_account.pem"
FILE_PRIVATE_KEY = "remote_private.pem"
FILE_FULLCHAIN = "remote_fullchain.pem"
FILE_REGISTRATION = "acme_reg.json"

ACME_SERVER = "https://acme-staging-v02.api.letsencrypt.org/directory"
ACCOUNT_KEY_SIZE = 2048
PRIVATE_KEY_SIZE = 2048
USER_AGENT = "home-assistant"

_LOGGER = logging.getLogger(__name__)


class AcmeClientError(Exception):
    """Raise if a acme client error raise."""


class AcmeChallengeError(AcmeClientError):
    """Raise if a challenge fails."""


@attr.s
class ChallengeHandler:
    """Handle ACME data over a challenge."""

    challenge = attr.ib(type=messages.ChallengeResource)
    order = attr.ib(type=messages.OrderResource)
    response = attr.ib(type=challenges.ChallengeResponse)
    validation = attr.ib(type=str)


class AcmeHandler:
    """Class handle a local certification."""

    def __init__(self, cloud, acme_server=None):
        """Initialize local ACME Handler."""
        self.cloud = cloud
        self._account_jwk = None
        self._acme_client = None
        self._acme_server = acme_server or ACME_SERVER

        self._domain = None
        self._email = None

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

    def _generate_csr(self) -> bytes:
        """Load or create private key."""
        if self.path_private_key.exists():
            _LOGGER.debug("Load private keyfile: %s", self.path_private_key)
            key_pem = self.path_account_key.read_bytes()
        else:
            _LOGGER.debug("create private keyfile: %s", self.path_private_key)
            key = OpenSSL.crypto.PKey()
            key.generate_key(OpenSSL.crypto.TYPE_RSA, PRIVATE_KEY_SIZE)
            key_pem = OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, key)

            self.path_private_key.write_bytes(key_pem)

        return crypto_util.make_csr(key_pem, [self._domain])

    def _load_account_key(self):
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

    def _create_client(self, email):
        """Create new ACME client."""
        if self.path_registration_info.exists():
            _LOGGER.info("Load exists ACME registration")
            regr = messages.RegistrationResource.json_loads(
                self.path_registration_info.read_text()
            )

            acme_url = urllib.parse.urlparse(ACME_SERVER)
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
                self._acme_client = client.ClientV2(self._acme_server, net=network)
            except errors.Error as err:
                _LOGGER.error("Can't connect to ACME server: %s", err)
                raise AcmeClientError() from None
            return

        # Create a new registration
        try:
            network = client.ClientNetwork(self._account_jwk, user_agent=USER_AGENT)
            self._acme_client = client.ClientV2(self._acme_server, net=network)
        except errors.Error as err:
            _LOGGER.error("Can't connect to ACME server: %s", err)
            raise AcmeClientError() from None

        try:
            _LOGGER.info(
                "Register a ACME account with TOS: %s",
                self._acme_client.directory.meta.terms_of_service,
            )
            regr = self._acme_client.new_account(
                messages.NewRegistration.from_data(
                    email=email, terms_of_service_agreed=True
                )
            )
        except errors.Error as err:
            _LOGGER.error("Can't register to ACME server: %s", err)
            raise AcmeClientError() from None

        # Store registration info
        self.path_registration_info.write_text(regr.json_dumps_pretty())
        self.path_registration_info.chmod(0o600)

    def _start_challenge(self, csr_pem) -> ChallengeHandler:
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
            raise AcmeChallengeError() from None

        try:
            order = self._acme_client.poll_and_finalize(handler.order)
        except errors.Error as err:
            _LOGGER.error("Wait of ACME challenge fails: %s", err)
            raise AcmeChallengeError() from None

        # Cleanup the old stuff
        if self.path_fullchain.exists():
            _LOGGER.info("Renew old certificate: %s", self.path_fullchain)
            self.path_fullchain.unlink()
        else:
            _LOGGER.info("Create new certificate: %s", self.path_fullchain)

        self.path_fullchain.write_bytes(order.fullchain_pem)
        self.path_fullchain.chmod(0o600)

    def _revoke_certificate(self):
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
            _LOGGER.error("Can't revoke certificate: %s", err)
            raise AcmeClientError() from None

        self.path_fullchain.unlink()
        self.path_private_key.unlink()

    def _deactivate_account():
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
            raise AcmeClientError() from None

        self.path_registration_info.unlink()
        self.path_account_key.unlink()

    async def async_instance_details(self):
        """Load user information."""
        async with async_timeout.timeout(10):
            resp = await cloud_api.async_remote_register(self.cloud)
            data = await resp.json()

        self._domain = data["domain"]
        self._email = data["email"]

    async def async_issue_certificate(self):
        """Create/Update certificate."""
        if not self._acme_client:
            await self.cloud.run_executor(self._create_client)

        # Initialize challenge / new certificate
        csr = await self.cloud.run_executor(self._generate_csr)
        challenge = await self.cloud.run_executor(self._start_challenge, csr)

        # Update DNS
        async with async_timeout.timeout(10):
            resp = await cloud_api.async_remote_challenge(
                self.cloud, challenge.validation
            )

        if resp.status != 200:
            _LOGGER.error("Can't set challenge token to NabuCasa DNS!")
            raise AcmeChallengeError()

        # Finish validation
        await self.cloud.run_executor(self._finish_challenge, challenge)

    async def async_remove_acme(self):
        """Revoke and deactivate acme certificate/account."""
        if not self._acme_client:
            await self.cloud.run_executor(self._create_client)

        await self.cloud.run_executor(self._revoke_certificate)
        await self.cloud.run_executor(self._deactivate_account)
