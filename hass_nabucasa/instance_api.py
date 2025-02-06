"""Manage instance API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, TypedDict

from aiohttp import hdrs

from .api import ApiBase, CloudApiError

_LOGGER = logging.getLogger(__name__)


class InstanceApiError(CloudApiError):
    """Exception raised when handling instance API."""


class InstanceConnectionDetails(TypedDict):
    """Connection details from instance API."""

    remote_ip_address: str
    connected_at: str


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

    async def connection(self) -> InstanceConnection:
        """Get the connection details."""
        _LOGGER.debug("Getting instance connection details")
        try:
            details: InstanceConnection = await self._call_cloud_api(
                path="/instance/connection",
                headers={
                    hdrs.AUTHORIZATION: self._cloud.access_token,
                },
            )
        except CloudApiError as err:
            raise InstanceApiError(err, orig_exc=err) from err
        return details
