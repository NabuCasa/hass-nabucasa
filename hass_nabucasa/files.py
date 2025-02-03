"""Manage cloud files."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
import logging
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from aiohttp import (
    ClientError,
    ClientTimeout,
    StreamReader,
)

from .api import ApiBase, CloudApiError, CloudApiNonRetryableError

_LOGGER = logging.getLogger(__name__)

_FILE_TRANSFER_TIMEOUT = 43200.0  # 43200s == 12h

type StorageType = Literal["backup"]


class FilesError(CloudApiError):
    """Exception raised when handling files."""


class _FilesHandlerUrlResponse(TypedDict):
    """URL Response from files handler."""

    url: str


class FilesHandlerDownloadDetails(_FilesHandlerUrlResponse):
    """Download details from files handler."""


class FilesHandlerUploadDetails(_FilesHandlerUrlResponse):
    """Upload details from files handler."""

    headers: dict[str, str]


class Files(ApiBase):
    """Class to help manage files."""

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        if TYPE_CHECKING:
            assert self._cloud.servicehandlers_server is not None
        return self._cloud.servicehandlers_server

    @property
    def non_retryable_error_codes(self) -> set[str]:
        """Get the non-retryable error codes."""
        return {"NC-SH-FH-03"}

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
            details: FilesHandlerUploadDetails = await self._call_cloud_api(
                path="/files/upload_details",
                jsondata={
                    "storage_type": storage_type,
                    "filename": filename,
                    "md5": base64md5hash,
                    "size": size,
                    "metadata": metadata,
                },
            )
        except CloudApiNonRetryableError:
            raise
        except CloudApiError as err:
            raise FilesError(err) from err

        try:
            response = await self._cloud.websession.put(
                details["url"],
                data=await open_stream(),
                headers=details["headers"] | {"content-length": str(size)},
                timeout=ClientTimeout(
                    connect=10.0, total=_FILE_TRANSFER_TIMEOUT),
            )
            self._do_log_response(response)

            response.raise_for_status()
        except TimeoutError as err:
            raise FilesError(
                "Timeout reached while trying to upload file") from err
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
            details: FilesHandlerDownloadDetails = await self._call_cloud_api(
                path=f"/files/download_details/{storage_type}/{filename}",
            )
        except CloudApiNonRetryableError:
            raise
        except CloudApiError as err:
            raise FilesError(err) from err

        try:
            response = await self._cloud.websession.get(
                details["url"],
                timeout=ClientTimeout(
                    connect=10.0, total=_FILE_TRANSFER_TIMEOUT),
            )

            self._do_log_response(response)

            response.raise_for_status()
        except FilesError:
            raise
        except TimeoutError as err:
            raise FilesError(
                "Timeout reached while trying to download file") from err
        except ClientError as err:
            raise FilesError("Failed to download file") from err
        except Exception as err:
            raise FilesError(
                "Unexpected error while downloading file") from err

        return response.content
