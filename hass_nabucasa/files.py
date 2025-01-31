"""Manage cloud files."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
import contextlib
from json import JSONDecodeError
import logging
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from aiohttp import (
    ClientError,
    ClientResponse,
    ClientTimeout,
    StreamReader,
    hdrs,
)

from .auth import CloudError

if TYPE_CHECKING:
    from . import Cloud, _ClientT

_LOGGER = logging.getLogger(__name__)

_FILE_TRANSFER_TIMEOUT = 43200.0  # 43200s == 12h
_NON_RETRYABLE_ERROR_CODES = {
    "NC-CE-02",
    "NC-CE-03",
    "NC-SH-FH-03",
}

type StorageType = Literal["backup"]


class FilesError(CloudError):
    """Exception raised when handling files."""


class FilesNonRetryableError(FilesError):
    """Exception raised when handling files that should not be retried."""

    def __init__(self, message: str, code: str) -> None:
        """Initialize."""
        super().__init__(message)
        self.code = code


class _FilesHandlerUrlResponse(TypedDict):
    """URL Response from files handler."""

    url: str


class FilesHandlerDownloadDetails(_FilesHandlerUrlResponse):
    """Download details from files handler."""


class FilesHandlerUploadDetails(_FilesHandlerUrlResponse):
    """Upload details from files handler."""

    headers: dict[str, str]


class Files:
    """Class to help manage files."""

    def __init__(
        self,
        cloud: Cloud[_ClientT],
    ) -> None:
        """Initialize cloudhooks."""
        self._cloud = cloud

    def _do_log_response(
        self,
        resp: ClientResponse,
        data: list[Any] | dict[Any, Any] | str | None = None,
    ) -> None:
        """Log the response."""
        isok = resp.status < 400
        target = (
            resp.url.path if resp.url.host == self._cloud.servicehandlers_server else ""
        )
        _LOGGER.log(
            logging.DEBUG if isok else logging.WARNING,
            "Response from %s%s (%s) %s",
            resp.url.host,
            target,
            resp.status,
            data["message"]
            if not isok and isinstance(data, dict) and "message" in data
            else "",
        )

    async def __call_files_api(
        self,
        *,
        method: str,
        path: str,
        jsondata: dict[str, Any] | None = None,
    ) -> Any:
        """Call cloud files API."""
        data: dict[str, Any] | list[Any] | str | None = None
        await self._cloud.auth.async_check_token()
        if TYPE_CHECKING:
            assert self._cloud.id_token is not None
            assert self._cloud.servicehandlers_server is not None

        resp = await self._cloud.websession.request(
            method=method,
            url=f"https://{self._cloud.servicehandlers_server}/files{path}",
            headers={
                hdrs.ACCEPT: "application/json",
                hdrs.AUTHORIZATION: self._cloud.id_token,
                hdrs.CONTENT_TYPE: "application/json",
                hdrs.USER_AGENT: self._cloud.client.client_name,
            },
            json=jsondata,
        )

        with contextlib.suppress(JSONDecodeError):
            data = await resp.json()

        self._do_log_response(resp, data)

        if data is None:
            raise FilesError("Failed to parse response from files handler") from None

        if (
            resp.status == 400
            and isinstance(data, dict)
            and (message := data.get("message"))
            and (code := message.split(" ")[0])
            and code in _NON_RETRYABLE_ERROR_CODES
        ):
            raise FilesNonRetryableError(message, code) from None

        resp.raise_for_status()
        return data

    async def upload(
        self,
        *,
        storage_type: StorageType,
        open_stream: Callable[[], Coroutine[Any, Any, AsyncIterator[bytes]]],
        filename: str,
        base64md5hash: str,
        size: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Upload a file."""
        _LOGGER.debug("Uploading file %s", filename)
        try:
            details: FilesHandlerUploadDetails = await self.__call_files_api(
                method="GET",
                path="/upload_details",
                jsondata={
                    "storage_type": storage_type,
                    "filename": filename,
                    "md5": base64md5hash,
                    "size": size,
                    "metadata": metadata,
                },
            )
        except FilesError:
            raise
        except TimeoutError as err:
            raise FilesError(
                "Timeout reached while trying to fetch upload details",
            ) from err
        except ClientError as err:
            raise FilesError(f"Failed to fetch upload details: {err}") from err
        except Exception as err:
            raise FilesError(
                f"Unexpected error while fetching upload details: {err}",
            ) from err

        try:
            response = await self._cloud.websession.put(
                details["url"],
                data=await open_stream(),
                headers=details["headers"] | {"content-length": str(size)},
                timeout=ClientTimeout(connect=10.0, total=_FILE_TRANSFER_TIMEOUT),
            )
            self._do_log_response(response)

            response.raise_for_status()
        except TimeoutError as err:
            raise FilesError("Timeout reached while trying to upload file") from err
        except ClientError as err:
            raise FilesError("Failed to upload file") from err
        except Exception as err:
            raise FilesError("Unexpected error while uploading file") from err

    async def download(
        self,
        storage_type: StorageType,
        filename: str,
    ) -> StreamReader:
        """Download a file."""
        _LOGGER.debug("Downloading file %s", filename)
        try:
            details: FilesHandlerDownloadDetails = await self.__call_files_api(
                method="GET",
                path=f"/download_details/{storage_type}/{filename}",
            )
        except FilesError:
            raise
        except TimeoutError as err:
            raise FilesError(
                "Timeout reached while trying to fetch download details",
            ) from err
        except ClientError as err:
            raise FilesError(f"Failed to fetch download details: {err}") from err
        except Exception as err:
            raise FilesError(
                f"Unexpected error while fetching download details: {err}",
            ) from err

        try:
            response = await self._cloud.websession.get(
                details["url"],
                timeout=ClientTimeout(connect=10.0, total=_FILE_TRANSFER_TIMEOUT),
            )

            self._do_log_response(response)

            response.raise_for_status()
        except FilesError:
            raise
        except TimeoutError as err:
            raise FilesError("Timeout reached while trying to download file") from err
        except ClientError as err:
            raise FilesError("Failed to download file") from err
        except Exception as err:
            raise FilesError("Unexpected error while downloading file") from err

        return response.content
