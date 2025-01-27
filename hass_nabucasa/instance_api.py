"""Manage instance API."""

from __future__ import annotations

import contextlib
from json import JSONDecodeError
import logging
from typing import TYPE_CHECKING, Any, TypedDict

from aiohttp import (
    ClientError,
    ClientResponse,
    ClientResponseError,
    hdrs,
)
from multidict import istr

from .auth import CloudError

if TYPE_CHECKING:
    from . import Cloud, _ClientT

_LOGGER = logging.getLogger(__name__)


class InstanceApiError(CloudError):
    """Exception raised when handling instance API."""


class InstanceConnection(TypedDict):
    """Connection details from instance API."""

    connected: bool


class InstanceApi:
    """Class to help communicate with the instance API."""

    def __init__(
        self,
        cloud: Cloud[_ClientT],
    ) -> None:
        """Initialize cloudhooks."""
        self._cloud = cloud

        if TYPE_CHECKING:
            assert cloud.servicehandlers_server is not None
        self._hostname = cloud.servicehandlers_server

    def _do_log_response(
        self,
        resp: ClientResponse,
        data: list[Any] | dict[Any, Any] | str | None = None,
    ) -> None:
        """Log the response."""
        isok = resp.status < 400
        target = resp.url.path if resp.url.host == self._hostname else ""
        _LOGGER.debug(
            "Response from %s%s (%s) %s",
            resp.url.host,
            target,
            resp.status,
            data["message"]
            if not isok and isinstance(data, dict) and "message" in data
            else "",
        )

    async def __call_instance_api(
        self,
        *,
        method: str,
        path: str,
        headers: dict[istr, str] | None = None,
    ) -> Any:
        """Call instance API."""
        data: dict[str, Any] | list[Any] | str | None = None
        await self._cloud.auth.async_check_token()
        if TYPE_CHECKING:
            assert self._cloud.id_token is not None

        resp = await self._cloud.websession.request(
            method=method,
            url=f"https://{self._hostname}/instance{path}",
            headers={
                hdrs.ACCEPT: "application/json",
                hdrs.AUTHORIZATION: self._cloud.id_token,
                hdrs.CONTENT_TYPE: "application/json",
                hdrs.USER_AGENT: self._cloud.client.client_name,
                **(headers or {}),
            },
        )

        with contextlib.suppress(JSONDecodeError):
            data = await resp.json()

        self._do_log_response(resp, data)

        if data is None:
            raise InstanceApiError(
                "Failed to parse response from instance API",
            ) from None

        resp.raise_for_status()
        return data

    async def connection(self) -> InstanceConnection:
        """Get the connection details."""
        _LOGGER.debug("Getting connection")
        try:
            details: InstanceConnection = await self.__call_instance_api(
                method="GET",
                path="/connection",
                headers={
                    hdrs.AUTHORIZATION: self._cloud.access_token,
                },
            )
        except TimeoutError as err:
            raise InstanceApiError(
                "Timeout reached while trying to fetch connections",
            ) from err
        except ClientResponseError as err:
            raise InstanceApiError(
                f"Failed to fetch connections: ({err.status}) {err.message}",
            ) from err
        except ClientError as err:
            raise InstanceApiError(
                f"Failed to fetch connections: {err}") from err
        except Exception as err:
            raise InstanceApiError(
                f"Unexpected error while getting connections: {err}",
            ) from err

        return details
