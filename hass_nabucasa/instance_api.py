"""Manage instance API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypedDict

from aiohttp import (
    hdrs,
)

from .api import ApiBase, CloudApiError

if TYPE_CHECKING:
    from . import Cloud, _ClientT

_LOGGER = logging.getLogger(__name__)


class InstanceApiError(CloudApiError):
    """Exception raised when handling instance API."""


class InstanceConnection(TypedDict):
    """Connection details from instance API."""

    connected: bool


class InstanceApi(ApiBase):
    """Class to help communicate with the instance API."""

    def __init__(
        self,
        cloud: Cloud[_ClientT],
    ) -> None:
        """Initialize instance API."""
        if TYPE_CHECKING:
            assert cloud.servicehandlers_server is not None
        super().__init__(cloud, hostname=cloud.servicehandlers_server)
        self._cloud = cloud

    async def connection(self) -> InstanceConnection:
        """Get the connection details."""
        _LOGGER.debug("Getting connection")
        try:
            details: InstanceConnection = await self._call_cloud_api(
                path="/connection",
                headers={
                    hdrs.AUTHORIZATION: self._cloud.access_token,
                },
            )
        except InstanceApiError as err:
            raise InstanceApiError(f"Failed to get connection {err}") from err
        return details
