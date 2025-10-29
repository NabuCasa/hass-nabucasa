"""Define the API base class."""

from __future__ import annotations

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
from aiohttp.typedefs import Query
import voluptuous as vol
from voluptuous.humanize import humanize_error
from yarl import URL

from .auth import Unauthenticated, UnknownError
from .exceptions import CloudError

if TYPE_CHECKING:
    from . import Cloud, _ClientT
    from .service_discovery import ServiceDiscoveryAction

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

DEFAULT_API_TIMEOUT = ClientTimeout(total=60)


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


class CloudApiInvalidResponseError(CloudApiError):
    """Exception raised when API response fails schema validation."""


@dataclass
class CloudApiRawResponse:
    """A raw response from the cloud API."""

    response: ClientResponse
    data: Any = None


class ApiBase:
    """Class to help communicate with the cloud API."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize the API base."""
        self._cloud = cloud

    @property
    def hostname(self) -> str | None:
        """Get the hostname for path-based API calls."""
        return None

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
        include_path_in_log: bool = True,
    ) -> None:
        """Log the response."""
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        url = url if isinstance(url, URL) else URL(url)
        target = url.path if include_path_in_log else ""
        _LOGGER.debug("Sending %s request to %s%s", method, url.host, target)

    def _do_log_response(
        self,
        resp: ClientResponse,
        data: list[Any] | dict[Any, Any] | str | None = None,
        include_path_in_log: bool = True,
    ) -> None:
        """Log the response."""
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        isok = resp.status < 400
        target = resp.url.path if include_path_in_log else ""
        if len(resp.url.query) > 0:
            allowed_values = {"true", "false"}
            query_params = [
                f"{key}=***"
                if value.lower() not in allowed_values
                else f"{key}={value}"
                for key, value in resp.url.query.items()
            ]
            target += f"?{'&'.join(query_params)}"
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
        params: Query | None = None,
        include_path_in_log: bool = True,
    ) -> ClientResponse:
        """Call raw API."""
        self._do_log_request(method, url, include_path_in_log)
        try:
            resp = await self._cloud.websession.request(
                method=method,
                url=url,
                timeout=client_timeout,
                headers=headers,
                json=jsondata,
                data=data,
                params=params,
            )
        except TimeoutError as err:
            raise CloudApiTimeoutError(
                f"Timeout reached while calling API: total allowed time is "
                f"{client_timeout.total} seconds",
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
        action: ServiceDiscoveryAction | None = None,
        action_values: dict[str, Any] | None = None,
        path: str | None = None,
        api_version: int | None = None,
        method: str = "GET",
        client_timeout: ClientTimeout | None = None,
        jsondata: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        skip_token_check: bool = False,
        raw_response: bool = False,
        params: Query | None = None,
        include_path_in_log: bool = True,
        schema: vol.Schema | None = None,
    ) -> Any:
        """Call cloud API."""
        if action is None and path is None:
            raise CloudApiError("Either 'action' or 'path' parameter must be provided")

        data: dict[str, Any] | list[Any] | str | None = None
        if not skip_token_check:
            await self._cloud.auth.async_check_token()
        if TYPE_CHECKING:
            assert self._cloud.id_token is not None

        if action is not None:
            final_url = self._cloud.service_discovery.action_url(
                action=action,
                **(action_values or {}),
            )
        else:
            url_path = f"{f'/v{api_version}' if api_version else ''}{path}"
            final_url = f"https://{self.hostname}{url_path}"

        resp = await self._call_raw_api(
            method=method,
            url=final_url,
            client_timeout=client_timeout or DEFAULT_API_TIMEOUT,
            headers={
                hdrs.ACCEPT: "application/json",
                hdrs.AUTHORIZATION: f"Bearer {self._cloud.id_token}",
                hdrs.CONTENT_TYPE: "application/json",
                hdrs.USER_AGENT: self._cloud.client.client_name,
                **(headers or {}),
            },
            jsondata=jsondata,
            params=params,
            include_path_in_log=include_path_in_log,
        )

        if resp.status < 500:
            with contextlib.suppress(ContentTypeError, JSONDecodeError):
                data = await resp.json()

        self._do_log_response(resp, data, include_path_in_log)

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

        if schema is not None and data is not None:
            try:
                data = schema(data)
            except vol.Invalid as err:
                raise CloudApiInvalidResponseError(
                    f"Invalid response: {humanize_error(data, err)}",
                    orig_exc=err,
                ) from err

        return data
