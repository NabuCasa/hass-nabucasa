"""Define the API base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine
import contextlib
from dataclasses import dataclass
from functools import wraps
from json import JSONDecodeError
import logging
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, final

from aiohttp import (
    ClientError,
    ClientResponse,
    ClientResponseError,
    ClientTimeout,
    ContentTypeError,
    hdrs,
)
from yarl import URL

from .auth import Unauthenticated, UnknownError
from .exceptions import CloudError

if TYPE_CHECKING:
    from . import Cloud, _ClientT

    P = ParamSpec("P")
    T = TypeVar("T")

_LOGGER = logging.getLogger(__name__)

ALLOW_EMPTY_RESPONSE = frozenset(
    {
        "DELETE",
        "POST",
        "HEAD",
    }
)


def api_exception_handler(
    exception: type[CloudApiError],
) -> Callable[
    [Callable[P, Awaitable[T]]],
    Callable[P, Coroutine[Any, Any, T]],
]:
    """Handle API exceptions."""

    def decorator(
        func: Callable[P, Awaitable[T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                return await func(*args, **kwargs)
            except (
                CloudApiNonRetryableError,
                CloudApiCodedError,
                exception,
            ):
                raise
            except CloudApiError as err:
                raise exception(
                    err,
                    orig_exc=err,
                    reason=err.reason,
                    status=err.status,
                ) from err
            except (UnknownError, Unauthenticated) as err:
                raise exception(err, orig_exc=err) from err
            except Exception as err:
                raise exception(
                    f"Unexpected error while calling API: {err}",
                    orig_exc=err,
                ) from err

        return wrapper

    return decorator


class CloudApiError(CloudError):
    """Exception raised when handling cloud API."""

    def __init__(
        self,
        context: str | Exception,
        *,
        orig_exc: Exception | None = None,
        reason: str | None = None,
        status: int | None = None,
    ) -> None:
        """Initialize."""
        super().__init__(context)
        self.orig_exc = orig_exc
        self.reason = reason
        self.status = status


class CloudApiCodedError(CloudApiError):
    """Exception raised when handling cloud API."""

    def __init__(self, context: str | Exception, *, code: str) -> None:
        """Initialize."""
        super().__init__(context)
        self.code = code


class CloudApiTimeoutError(CloudApiError):
    """Exception raised when handling cloud API times out."""


class CloudApiClientError(CloudApiError):
    """Exception raised when handling cloud API client error."""


class CloudApiNonRetryableError(CloudApiCodedError):
    """Exception raised when handling cloud API non-retryable error."""


@dataclass
class CloudApiRawResponse:
    """A raw response from the cloud API."""

    response: ClientResponse
    data: Any = None


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

    def _do_log_request(
        self,
        method: str,
        url: str | URL,
    ) -> None:
        """Log the response."""
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        url = url if isinstance(url, URL) else URL(url)
        target = url.path if url.host == self.hostname else ""
        _LOGGER.debug("Sending %s request to %s%s", method, url.host, target)

    def _do_log_response(
        self,
        resp: ClientResponse,
        data: list[Any] | dict[Any, Any] | str | None = None,
    ) -> None:
        """Log the response."""
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        isok = resp.status < 400
        target = resp.url.path if resp.url.host == self.hostname else ""
        _LOGGER.debug(
            "Response for %s from %s%s (%s) %s",
            resp.method,
            resp.url.host,
            target,
            resp.status,
            data["reason"]
            if not isok and isinstance(data, dict) and "reason" in data
            else data["message"]
            if not isok and isinstance(data, dict) and "message" in data
            else "",
        )

    async def _call_raw_api(
        self,
        *,
        url: str,
        method: str,
        client_timeout: ClientTimeout,
        headers: dict[str, Any],
        jsondata: dict[str, Any] | None = None,
        data: Any | None = None,
    ) -> ClientResponse:
        """Call raw API."""
        self._do_log_request(method, url)
        try:
            resp = await self._cloud.websession.request(
                method=method,
                url=url,
                timeout=client_timeout,
                headers=headers,
                json=jsondata,
                data=data,
            )
        except TimeoutError as err:
            raise CloudApiTimeoutError(
                "Timeout reached while calling API",
                orig_exc=err,
            ) from err
        except ClientResponseError as err:
            raise CloudApiClientError(
                f"Failed to fetch: ({err.status}) {err.message}",
                orig_exc=err,
                status=err.status,
            ) from err
        except ClientError as err:
            raise CloudApiClientError(f"Failed to fetch: {err}", orig_exc=err) from err
        except Exception as err:
            raise CloudApiError(
                f"Unexpected error while calling API: {err}",
                orig_exc=err,
            ) from err

        return resp

    async def _call_cloud_api(
        self,
        *,
        path: str,
        method: str = "GET",
        api_version: int | None = None,
        client_timeout: ClientTimeout | None = None,
        jsondata: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        skip_token_check: bool = False,
        raw_response: bool = False,
    ) -> Any:
        """Call cloud API."""
        data: dict[str, Any] | list[Any] | str | None = None
        if not skip_token_check:
            await self._cloud.auth.async_check_token()
        if TYPE_CHECKING:
            assert self._cloud.id_token is not None

        url_path = f"{f'/v{api_version}' if api_version else ''}{path}"

        resp = await self._call_raw_api(
            method=method,
            url=f"https://{self.hostname}{url_path}",
            client_timeout=client_timeout or ClientTimeout(total=10),
            headers={
                hdrs.ACCEPT: "application/json",
                hdrs.AUTHORIZATION: f"Bearer {self._cloud.id_token}",
                hdrs.CONTENT_TYPE: "application/json",
                hdrs.USER_AGENT: self._cloud.client.client_name,
                **(headers or {}),
            },
            jsondata=jsondata,
        )

        if resp.status < 500:
            with contextlib.suppress(ContentTypeError, JSONDecodeError):
                data = await resp.json()

        self._do_log_response(resp, data)

        if data is None and resp.method.upper() not in ALLOW_EMPTY_RESPONSE:
            raise CloudApiError("Failed to parse API response") from None

        if (
            resp.status == 400
            and isinstance(data, dict)
            and (message := data.get("message"))
            and (code := message.split(" ")[0])
            and code in self._non_retryable_error_codes
        ):
            raise CloudApiNonRetryableError(message, code=code) from None

        if resp.status == 403 and self._cloud.subscription_expired:
            raise CloudApiNonRetryableError(
                "Subscription has expired",
                code="subscription_expired",
            ) from None

        if raw_response:
            return CloudApiRawResponse(data=data, response=resp)

        try:
            resp.raise_for_status()
        except ClientResponseError as err:
            reason = (
                data.get("reason", data.get("message"))
                if isinstance(data, dict)
                else None
            )
            raise CloudApiError(
                f"Failed to fetch: ({err.status}) {err.message}",
                orig_exc=err,
                reason=reason,
                status=resp.status,
            ) from err
        return data
