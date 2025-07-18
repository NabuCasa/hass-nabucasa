"""Manage instance API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, TypedDict

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


class InstanceApi(ApiBase):
    """Class to help communicate with the instance API."""

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        if TYPE_CHECKING:
            assert self._cloud.servicehandlers_server is not None
        return self._cloud.servicehandlers_server

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
            path="/instance/connection",
            headers={
                hdrs.AUTHORIZATION: access_token or self._cloud.access_token,
            },
            skip_token_check=skip_token_check,
        )
        return details

    @api_exception_handler(InstanceApiError)
    async def resolve_dns_cname(self, *, hostname: str) -> list[str]:
        """Resolve DNS CNAME."""
        details: list[str] = await self._call_cloud_api(
            method="POST",
            path="/instance/resolve_dns_cname",
            jsondata={"hostname": hostname},
        )
        return details

    @api_exception_handler(InstanceApiError)
    async def cleanup_dns_challenge_record(self, *, value: str) -> None:
        """Remove DNS challenge."""
        await self._call_cloud_api(
            method="POST",
            path="/instance/dns_challenge_cleanup",
            jsondata={"txt": value},
        )

    @api_exception_handler(InstanceApiError)
    async def create_dns_challenge_record(self, *, value: str) -> None:
        """Set DNS challenge."""
        await self._call_cloud_api(
            method="POST",
            path="/instance/dns_challenge_txt",
            jsondata={"txt": value},
        )
