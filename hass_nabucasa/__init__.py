"""Component to integrate the Home Assistant cloud."""
import asyncio
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
from typing import Callable, Coroutine

import aiohttp

from .client import CloudClient
from .cloudhooks import Cloudhooks
from .auth import CognitoAuth
from .const import CONFIG_DIR, MODE_DEV, SERVERS, STATE_CONNECTED
from .iot import CloudIoT
from .remote import RemoteUI
from .utils import parse_date, utcnow, UTC

_LOGGER = logging.getLogger(__name__)


class Cloud:
    """Store the configuration of the cloud connection."""

    def __init__(
        self,
        client: CloudClient,
        mode: str,
        cognito_client_id=None,
        user_pool_id=None,
        region=None,
        relayer=None,
        google_actions_sync_url=None,
        subscription_info_url=None,
        cloudhook_create_url=None,
        remote_api_url=None,
        acme_directory_server=None,
    ):
        """Create an instance of Cloud."""
        self.mode = mode
        self.client = client
        self.id_token = None
        self.access_token = None
        self.refresh_token = None
        self.iot = CloudIoT(self)
        self.cloudhooks = Cloudhooks(self)
        self.remote = RemoteUI(self)
        self.auth = CognitoAuth(self)

        if mode == MODE_DEV:
            self.cognito_client_id = cognito_client_id
            self.user_pool_id = user_pool_id
            self.region = region
            self.relayer = relayer
            self.google_actions_sync_url = google_actions_sync_url
            self.subscription_info_url = subscription_info_url
            self.cloudhook_create_url = cloudhook_create_url
            self.remote_api_url = remote_api_url
            self.acme_directory_server = acme_directory_server

        else:
            info = SERVERS[mode]

            self.cognito_client_id = info["cognito_client_id"]
            self.user_pool_id = info["user_pool_id"]
            self.region = info["region"]
            self.relayer = info["relayer"]
            self.google_actions_sync_url = info["google_actions_sync_url"]
            self.subscription_info_url = info["subscription_info_url"]
            self.cloudhook_create_url = info["cloudhook_create_url"]
            self.remote_api_url = info["remote_api_url"]
            self.acme_directory_server = info["acme_directory_server"]

    @property
    def is_logged_in(self) -> bool:
        """Get if cloud is logged in."""
        return self.id_token is not None

    @property
    def is_connected(self) -> bool:
        """Return True if we are connected."""
        return self.iot.state == STATE_CONNECTED

    @property
    def websession(self) -> aiohttp.ClientSession:
        """Return websession for connections."""
        return self.client.websession

    @property
    def subscription_expired(self) -> bool:
        """Return a boolean if the subscription has expired."""
        return utcnow() > self.expiration_date + timedelta(days=7)

    @property
    def expiration_date(self) -> datetime:
        """Return the subscription expiration as a UTC datetime object."""
        return datetime.combine(
            parse_date(self.claims["custom:sub-exp"]), datetime.min.time()
        ).replace(tzinfo=UTC)

    @property
    def claims(self):
        """Return the claims from the id token."""
        return self._decode_claims(self.id_token)

    @property
    def user_info_path(self) -> Path:
        """Get path to the stored auth."""
        return self.path("{}_auth.json".format(self.mode))

    def path(self, *parts) -> Path:
        """Get config path inside cloud dir.

        Async friendly.
        """
        return Path(self.client.base_path, CONFIG_DIR, *parts)

    def run_task(self, coro: Coroutine) -> Coroutine:
        """Schedule a task.

        Return a coroutine.
        """
        return self.client.loop.create_task(coro)

    def run_executor(self, callback: Callable, *args) -> asyncio.Future:
        """Run function inside executore.

        Return a awaitable object.
        """
        return self.client.loop.run_in_executor(None, callback, *args)

    async def fetch_subscription_info(self):
        """Fetch subscription info."""
        await self.run_executor(self.auth.check_token)
        return await self.websession.get(
            self.subscription_info_url, headers={"authorization": self.id_token}
        )

    async def logout(self) -> None:
        """Close connection and remove all credentials."""
        await self.iot.disconnect()

        self.id_token = None
        self.access_token = None
        self.refresh_token = None

        # Cleanup auth data
        if self.user_info_path.exists():
            await self.run_executor(self.user_info_path.unlink)

        await self.client.cleanups()

    def write_user_info(self) -> None:
        """Write user info to a file."""
        self.user_info_path.write_text(
            json.dumps(
                {
                    "id_token": self.id_token,
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                },
                indent=4,
            )
        )

    async def start(self):
        """Start the cloud component."""

        def load_config():
            """Load config."""
            # Ensure config dir exists
            base_path = self.path()
            if not base_path.exists():
                base_path.mkdir()

            if not self.user_info_path.exists():
                return None
            return json.loads(self.user_info_path.read_text())

        info = await self.run_executor(load_config)

        if info is None:
            return

        self.id_token = info["id_token"]
        self.access_token = info["access_token"]
        self.refresh_token = info["refresh_token"]

        self.run_task(self.iot.connect())

    async def stop(self):
        """Stop the cloud component."""
        await self.iot.disconnect()

    def _decode_claims(self, token):  # pylint: disable=no-self-use
        """Decode the claims in a token."""
        from jose import jwt

        return jwt.get_unverified_claims(token)
