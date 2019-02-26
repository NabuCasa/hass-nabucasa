"""Handle ACME and local certificates."""
from pathlib import Path
import logging

import acme.client
import acme.messages
import acme.challenges
from acme import jose
import async_timeout
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from . import cloud_api

FILE_PRIVATE_KEY = "ssl_key.pem"
FILE_REGISTRATION = "acme_reg.json"

ACME_SERVER = "https://acme-v01.api.letsencrypt.org/directory"
ACCOUNT_KEY_SIZE = 2048

_LOGGER = logging.getLogger(__name__)


class AcmeHandler:
    """Class handle a local certification."""

    def __init__(self, cloud):
        """Initialize local ACME Handler."""
        self.cloud = cloud
        self._private_jwk = None
        self._acme_client = None
        self._acme_regr = None
        self._acme_challg = None

    @property
    def path_private_key(self) -> Path:
        """Return path of private key."""
        return Path(self.cloud.path(FILE_PRIVATE_KEY))

    @property
    def path_registration_info(self) -> Path:
        """Return path of acme client registration file."""
        return Path(self.cloud.path(FILE_REGISTRATION))

    def _load_private_key(self):
        """Load keys from store."""
        if self._private_jwk:
            return

        # Load or create a new
        key = None
        if self.path_private_key.exists():
            _LOGGER.debug("Load RSA keyfile: %s", self.path_private_key)
            pem = self.path_private_key.read_bytes()
            key = serialization.load_pem_private_key(
                pem, password=None, backend=default_backend())

        else:
            _LOGGER.debug("Create new RSA keyfile: %s", self.path_private_key)
            key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=ACCOUNT_KEY_SIZE,
                backend=default_backend()
            )

            # Store it to file
            pem = key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            self.path_private_key.write_bytes(pem)
            self.path_private_key.chmod(0o600)

        self._private_jwk = jose.JWKRSA(key=jose.ComparableRSAKey(key))

    def _register_client(self):
        """Register or validate a acme client."""

        if self.path_registration_info.exists():
            _LOGGER.debug("Update exists ACME registration")
            regr = acme.messages.RegistrationResource.json_loads(
                self.path_registration_info.read_text())

            try:
                regr = self._acme_client.query_registration(regr)
            except acme.messages.Error as err:
                _LOGGER.error("Can't validate exists validation: %s", err)
                raise

        else:
            _LOGGER.debug("Create new ACME registration")
            regr = self._acme_client.register()

        # Register/Update ACME registration
        self._acme_regr = self._acme_client.update_registration(
            regr.update(body=regr.body.update(agreement=regr.terms_of_service))
        )

        # Store registration
        self.path_registration_info.write_text(
            self._acme_regr.json_dumps_pretty())

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
                    domain, self._acme_regr.new_authzr_uri)
            except acme.messages.Error as err:
                _LOGGER.error(
                    "Can't initialize ACME challenge for %s: %s", domain, err)
                raise

    async def async_init_client(self):
        """Create an account by ACME provider."""
        # Get private key
        await self.cloud.hass.async_add_executor_job(self._load_private_key)

        # Create acme client
        self._acme_client = acme.client.Client(ACME_SERVER, self._private_jwk)

        # Register client
        await self.cloud.hass.async_add_executor_job(self._register_client)

    async def async_issue_certificate(self):
        """Create or update certificate."""
        async with async_timeout.timeout(10):
            resp = await cloud_api.async_remote_register(self.cloud)
            data = await resp.json()
        domain = data["domain"]

        # Start challenge
        await self.cloud.hass.async_add_executor_job(
            self._init_challenge, domain)

