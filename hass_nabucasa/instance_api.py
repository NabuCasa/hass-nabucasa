"""Manage instance API."""

from __future__ import annotations

import logging
from typing import Literal, NotRequired, TypedDict

from aiohttp import hdrs

from .api import ApiBase, CloudApiError, api_exception_handler

_LOGGER = logging.getLogger(__name__)


class InstanceApiError(CloudApiError):
    """Exception raised when handling instance API."""


class InstanceConnectionDetails(TypedDict):
    """Connection details from instance API."""

    connected_at: str
    name: str
    remote_ip_address: str
    version: str


class InstanceConnectionConnnected(TypedDict):
    """Connection details from instance API."""

    connected: Literal[True]
    details: InstanceConnectionDetails


class InstanceConnectionDisconnected(TypedDict):
    """Connection details from instance API."""

    connected: Literal[False]


type InstanceConnection = InstanceConnectionConnnected | InstanceConnectionDisconnected


class InstanceRegistrationDetails(TypedDict):
    """Registration details from instance API."""

    alias: NotRequired[list[str]]
    domain: str
    email: str
    server: str


class InstanceSnitunTokenDetails(TypedDict):
    """Snitun token details from instance API."""

    token: str
    server: str
    valid: int
    throttling: int


class InstanceApi(ApiBase):
    """Class to help communicate with the instance API."""

    @api_exception_handler(InstanceApiError)
    async def connection(
        self,
        *,
        access_token: str | None = None,
        skip_token_check: bool = False,
    ) -> InstanceConnection:
        """Get the connection details."""
        _LOGGER.debug("Getting instance connection details")
        details: InstanceConnection = await self._call_cloud_api(
            action="instance_connection",
            headers={
                hdrs.AUTHORIZATION: access_token or self._cloud.access_token,
            },
            skip_token_check=skip_token_check,
        )
        return details

    @api_exception_handler(InstanceApiError)
    async def cleanup_dns_challenge_record(self, *, value: str) -> None:
        """Remove DNS challenge."""
        await self._call_cloud_api(
            method="POST",
            action="remote_access_dns_challenge_remove",
            jsondata={"txt": value},
        )

    @api_exception_handler(InstanceApiError)
    async def create_dns_challenge_record(self, *, value: str) -> None:
        """Set DNS challenge."""
        await self._call_cloud_api(
            method="POST",
            action="remote_access_dns_challenge_set",
            jsondata={"txt": value},
        )

    @api_exception_handler(InstanceApiError)
    async def register(self) -> InstanceRegistrationDetails:
        """Register the instance."""
        details: InstanceRegistrationDetails = await self._call_cloud_api(
            method="POST",
            action="remote_access_register",
        )
        return details

    @api_exception_handler(InstanceApiError)
    async def snitun_token(
        self,
        *,
        aes_key: bytes,
        aes_iv: bytes,
    ) -> InstanceSnitunTokenDetails:
        """Create a remote snitun token."""
        details: InstanceSnitunTokenDetails = await self._call_cloud_api(
            method="POST",
            action="remote_access_snitun_token",
            jsondata={"aes_key": aes_key.hex(), "aes_iv": aes_iv.hex()},
        )
        return details
