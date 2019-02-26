"""Handle ACME and local certificates."""
import logging
from pathlib import Path
import urllib

import OpenSSL
from acme import challenges, client, errors, messages
import async_timeout
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import josepy as jose

from . import cloud_api

FILE_ACCOUNT_KEY = "acme_account.pem"
FILE_PRIVATE_KEY = "private.pem"
FILE_REGISTRATION = "acme_reg.json"

ACME_SERVER = "https://acme-staging-v02.api.letsencrypt.org/directory"
ACCOUNT_KEY_SIZE = 2048
PRIVATE_KEY_SIZE = 2048
USER_AGENT = "home-assistant"

_LOGGER = logging.getLogger(__name__)


class AcmeClientError(Exception):
    """Raise if a acme client error raise."""


class AcmeHandler:
    """Class handle a local certification."""

    def __init__(self, cloud):
        """Initialize local ACME Handler."""
        self.cloud = cloud
        self._account_jwk = None
        self._acme_client = None

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
    def path_registration_info(self) -> Path:
        """Return path of acme client registration file."""
        return Path(self.cloud.path(FILE_REGISTRATION))

    def _generate_csr(self):
        """Load or create private key."""
        if self.path_private_key.exists():
            _LOGGER.debug("Load private keyfile: %s", self.path_private_key)
            pkey_pem = self.path_account_key.read_bytes()
        else:
            _LOGGER.debug("create private keyfile: %s", self.path_private_key)
            pkey = OpenSSL.crypto.PKey()
            pkey.generate_key(OpenSSL.crypto.TYPE_RSA, PRIVATE_KEY_SIZE)
            pkey_pem = OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, pkey)

            self.path_private_key.write_bytes(pkey_pem)

        return crypto_util.make_csr(pkey_pem, [self._domain])

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
                self._acme_client = client.ClientV2(ACME_SERVER, net=network)
            except errors.Error as err:
                _LOGGER.error("Can't connect to ACME server: %s", err)
                raise AcmeClientError() from None
            return

        # Create a new registration
        try:
            network = client.ClientNetwork(self._account_jwk, user_agent=USER_AGENT)
            self._acme_client = client.ClientV2(ACME_SERVER, net=network)
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

    def _init_challenge(self, domain: str):
        """Initialize domain challenge."""
        if self._acme_challg:
            _LOGGER.debug("Update exists ACME challenge")
            try:
                self._acme_client.poll(self._acme_challg)
            except acme.messages.Error as err:
                _LOGGER.error("Can't update ACME challenge!")
                self._acme_challg = None
                raise

        else:
            _LOGGER.debug("Start new ACME challenge")
            try:
                self._acme_challg = self._acme_client.request_domain_challenges(
                    domain, self._acme_regr.new_authzr_uri
                )
            except acme.messages.Error as err:
                _LOGGER.error("Can't initialize ACME challenge for %s: %s", domain, err)
                raise

    async def async_instance_details(self):
        """Load user information."""
        async with async_timeout.timeout(10):
            resp = await cloud_api.async_remote_register(self.cloud)
            data = await resp.json()

        self._domain = data["domain"]
        self._email = data["email"]

    async def async_issue_certificate(self):
        """Create/Update certificate."""

