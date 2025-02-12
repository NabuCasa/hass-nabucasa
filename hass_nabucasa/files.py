"""Manage cloud files."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
import contextlib
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any, TypedDict

from aiohttp import (
    ClientResponseError,
    ClientTimeout,
    StreamReader,
)

from .api import ApiBase, CloudApiError, CloudApiNonRetryableError

_LOGGER = logging.getLogger(__name__)

_FILE_TRANSFER_TIMEOUT = 43200.0  # 43200s == 12h


class StorageType(StrEnum):
    """Storage types."""

    BACKUP = "backup"


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


class StoredFile(TypedDict):
    """Stored file."""

    Key: str
    Size: int
    LastModified: str
    Metadata: dict[str, Any]


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
        _LOGGER.debug("Uploading %s file with name %s", storage_type, filename)
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
            raise FilesError(err, orig_exc=err) from err

        try:
            response = await self._call_raw_api(
                method="PUT",
                url=details["url"],
                data=await open_stream(),
                headers=details["headers"] | {"content-length": str(size)},
                client_timeout=ClientTimeout(
                    connect=10.0,
                    total=_FILE_TRANSFER_TIMEOUT,
                ),
            )

            self._do_log_response(response)
            if response.status == 400:
                # We can try to get some context.
                error = await response.text()
                if error and "<Message>" in error and "</Message>" in error:
                    with contextlib.suppress(AttributeError, IndexError):
                        # This is ugly but it's the best we can do, we have no control
                        # over the error message structure, so we try what we can.
                        parsed = (
                            error.split("<Message>")[1]
                            .split("</Message>")[0]
                            .replace("\n", " ")
                        )
                        raise FilesError(f"Failed to upload: (400) {parsed}")
                _LOGGER.debug(error)
            response.raise_for_status()
        except CloudApiError as err:
            raise FilesError(err, orig_exc=err) from err
        except ClientResponseError as err:
            raise FilesError(
                f"Failed to upload: ({err.status}) {err.message}",
                orig_exc=err,
            ) from err

    async def download(
        self,
        storage_type: StorageType,
        filename: str,
    ) -> StreamReader:
        """Download a file."""
        _LOGGER.debug("Downloading %s file with name %s", storage_type, filename)
        try:
            details: FilesHandlerDownloadDetails = await self._call_cloud_api(
                path=f"/files/download_details/{storage_type}/{filename}",
            )
        except CloudApiNonRetryableError:
            raise
        except CloudApiError as err:
            raise FilesError(err, orig_exc=err) from err

        try:
            response = await self._call_raw_api(
                method="GET",
                headers={},
                url=details["url"],
                client_timeout=ClientTimeout(
                    connect=10.0,
                    total=_FILE_TRANSFER_TIMEOUT,
                ),
            )

            self._do_log_response(response)
            response.raise_for_status()
        except CloudApiError as err:
            raise FilesError(err, orig_exc=err) from err
        except ClientResponseError as err:
            raise FilesError(
                f"Failed to download: ({err.status}) {err.message}",
                orig_exc=err,
            ) from err

        return response.content

    async def list(
        self,
        storage_type: StorageType,
    ) -> list[StoredFile]:
        """List files."""
        _LOGGER.debug("Listing %s files", storage_type)
        try:
            files: list[StoredFile] = await self._call_cloud_api(
                path=f"/files/{storage_type}"
            )
        except CloudApiError as err:
            raise FilesError(err, orig_exc=err) from err
        return files

    async def delete(
        self,
        storage_type: StorageType,
        filename: str,
    ) -> None:
        """Delete a file."""
        _LOGGER.debug("Deleting %s file with name %s", storage_type, filename)
        try:
            await self._call_cloud_api(
                path="/files",
                method="DELETE",
                jsondata={
                    "storage_type": storage_type,
                    "filename": filename,
                },
            )
        except CloudApiError as err:
            raise FilesError(err, orig_exc=err) from err
