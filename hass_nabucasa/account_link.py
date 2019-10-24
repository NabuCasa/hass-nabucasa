"""Helpers to help with account linking."""
import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from aiohttp.client_ws import ClientWebSocketResponse

if TYPE_CHECKING:
    from . import Cloud

_LOGGER = logging.getLogger(__name__)

# Each function can only be called once.
ERR_ALREADY_CONSUMED = "already_consumed"

# If the specified service is not supported
ERR_UNSUPORTED = "unsupported"

# If authorizing is currently unavailable
ERR_UNAVAILABLE = "unavailable"

# If we try to get tokens without being connected.
ERR_NOT_CONNECTED = "not_connected"

# Unknown error
ERR_UNKNOWN = "unknown"

# This error will be converted to asyncio.TimeoutError
ERR_TIMEOUT = "timeout"


class AccountLinkException(Exception):
    """Base exception for when account link errors happen."""

    def __init__(self, code: str):
        """Initialize the exception."""
        super().__init__(code)
        self.code = code


def _update_token_response(tokens, service):
    """Update token response in place."""
    tokens["service"] = service


class AuthorizeAccountHelper:
    """Class to help the user authorize a third party account with Home Assistant."""

    def __init__(self, cloud: "Cloud", service: str):
        """Initialize the authorize account helper."""
        self.cloud = cloud
        self.service = service
        self._client: Optional[ClientWebSocketResponse] = None

    async def async_get_authorize_url(self) -> str:
        """Generate the url where the user can authorize Home Assistant."""
        if self._client is not None:
            raise AccountLinkException(ERR_ALREADY_CONSUMED)

        _LOGGER.debug("Opening connection for %s", self.service)

        self._client = await self.cloud.client.websession.ws_connect(
            f"{self.cloud.account_link_url}/v1"
        )
        await self._client.send_json({"service": self.service})

        try:
            response = await self._get_response()
        except asyncio.CancelledError:
            await self._client.close()
            self._client = None
            raise

        return response["authorize_url"]

    async def async_get_tokens(self) -> dict:
        """Return the tokens when the user finishes authorizing."""
        if self._client is None:
            raise AccountLinkException(ERR_NOT_CONNECTED)

        try:
            response = await self._get_response()
        finally:
            await self._client.close()
            self._client = None

        _LOGGER.debug("Received tokens for %s", self.service)

        _update_token_response(response["tokens"], self.service)
        return response["tokens"]

    async def _get_response(self) -> dict:
        """Read a response from the connection and handle errors."""
        response = await self._client.receive_json()

        if "error" in response:
            if response["error"] == ERR_TIMEOUT:
                raise asyncio.TimeoutError()

            raise AccountLinkException(response["error"])

        return response


async def async_fetch_access_token(cloud: "Cloud", service: str, refresh_token: str):
    """Fetch access tokens using a refresh token."""
    _LOGGER.debug("Fetching tokens for %s", service)
    resp = await cloud.client.websession.post(
        f"{cloud.account_link_url}/refresh_token/{service}",
        json={"refresh_token": refresh_token},
    )
    resp.raise_for_status()
    tokens = await resp.json()
    _update_token_response(tokens, service)
    return tokens


async def async_fetch_available_services(cloud: "Cloud"):
    """Fetch available services."""
    resp = await cloud.client.websession.post(f"{cloud.account_link_url}/services")
    resp.raise_for_status()
    return await resp.json()
