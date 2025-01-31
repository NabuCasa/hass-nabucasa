"""Define the API base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
import contextlib
from json import JSONDecodeError
import logging
from typing import TYPE_CHECKING, Any, final

from aiohttp import (
    ClientError,
    ClientResponse,
    ClientResponseError,
    ClientTimeout,
    hdrs,
)

from .auth import CloudError

if TYPE_CHECKING:
    from . import Cloud, _ClientT

_LOGGER = logging.getLogger(__name__)


class CloudApiError(CloudError):
    """Exception raised when handling cloud API."""


class CloudApiRetryableError(CloudApiError):
    """Exception raised when handling cloud API that should be retried."""

    def __init__(self, message: str, code: str) -> None:
        """Initialize."""
        super().__init__(message)
        self.code = code


class ApiBase(ABC):
    """Class to help communicate with the cloud API."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize the API base."""
        self._cloud = cloud

    @property
    @abstractmethod
    def hostname(self) -> str:
        """Get the hostname."""

    @property
    def non_retryable_error_codes(self) -> set[str]:
        """Get the non-retryable error codes."""
        return set()

    @property
    @final
    def _non_retryable_error_codes(self) -> set[str]:
        """Get the non-retryable error codes."""
        return {"NC-CE-02", "NC-CE-03"}.union(self.non_retryable_error_codes)

    def _do_log_response(
        self,
        resp: ClientResponse,
        data: list[Any] | dict[Any, Any] | str | None = None,
    ) -> None:
        """Log the response."""
        isok = resp.status < 400
        target = resp.url.path if resp.url.host == self.hostname else ""
        _LOGGER.debug(
            "Response from %s%s (%s) %s",
            resp.url.host,
            target,
            resp.status,
            data["message"]
            if not isok and isinstance(data, dict) and "message" in data
            else "",
        )

    async def _call_cloud_api(
        self,
        *,
        path: str,
        method: str = "GET",
        client_timeout: ClientTimeout | None = None,
        jsondata: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
    ) -> Any:
        """Call cloud API."""
        data: dict[str, Any] | list[Any] | str | None = None
        await self._cloud.auth.async_check_token()
        if TYPE_CHECKING:
            assert self._cloud.id_token is not None

        try:
            resp = await self._cloud.websession.request(
                method=method,
                url=f"https://{self.hostname}{path}",
                timeout=client_timeout or ClientTimeout(total=10),
                headers={
                    hdrs.ACCEPT: "application/json",
                    hdrs.AUTHORIZATION: self._cloud.id_token,
                    hdrs.CONTENT_TYPE: "application/json",
                    hdrs.USER_AGENT: self._cloud.client.client_name,
                    **(headers or {}),
                },
                json=jsondata,
            )

        except TimeoutError as err:
            raise CloudApiError(
                "Timeout reached while calling API",
            ) from err
        except ClientResponseError as err:
            raise CloudApiError(
                f"Failed to fetch: ({err.status}) {err.message}",
            ) from err
        except ClientError as err:
            raise CloudApiError(f"Failed to fetch: {err}") from err
        except Exception as err:
            raise CloudApiError(
                f"Unexpected error while calling API: {err}",
            ) from err

        if resp.status < 500:
            with contextlib.suppress(JSONDecodeError):
                data = await resp.json()

        self._do_log_response(resp, data)

        if data is None:
            raise CloudApiError("Failed to parse API response") from None

        if (
            resp.status == 400
            and isinstance(data, dict)
            and (message := data.get("message"))
            and (code := message.split(" ")[0])
            and code in self._non_retryable_error_codes
        ):
            raise CloudApiRetryableError(message, code) from None

        try:
            resp.raise_for_status()
        except ClientResponseError as err:
            raise CloudApiError(
                f"Failed to fetch: ({err.status}) {err.message}",
            ) from err
        return data
