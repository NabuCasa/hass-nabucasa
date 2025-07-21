"""Manage cloud files."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Callable, Coroutine
import contextlib
from enum import StrEnum
import hashlib
import logging
from typing import TYPE_CHECKING, Any, TypedDict

from aiohttp import (
    ClientResponseError,
    ClientTimeout,
    StreamReader,
)

from .api import (
    ApiBase,
    CloudApiError,
    CloudApiNonRetryableError,
    api_exception_handler,
)

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


async def calculate_b64md5(
    open_stream: Callable[[], Coroutine[Any, Any, AsyncIterator[bytes]]],
    size: int,
) -> str:
    """Calculate the MD5 hash of a file.

    Raises FilesError if the bytes read from the stream does not match the size.
    """
    file_hash = hashlib.md5()  # noqa: S324 Disable warning about using md5
    bytes_read = 0
    stream = await open_stream()
    async for chunk in stream:
        bytes_read += len(chunk)
        file_hash.update(chunk)
    if bytes_read != size:
        raise FilesError(
            f"Indicated size {size} does not match actual size {bytes_read}"
        )
    return base64.b64encode(file_hash.digest()).decode()


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
            if 400 <= (status := response.status) < 500:
                # We can try to get some context.
                error = await response.text()
                if error and "<Message>" in error and "</Message>" in error:
                    with contextlib.suppress(AttributeError, IndexError):
                        # This is ugly but it's the best we can do, we have no control
                        # over the error message structure, so we try what we can.
                        error = error.split("<Message>")[1].split("</Message>")[0]
                raise FilesError(
                    f"Failed to upload: ({status}) {error[:256].replace('\n', ' ')}"
                )
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

    @api_exception_handler(FilesError)
    async def list(
        self,
        storage_type: StorageType,
    ) -> list[StoredFile]:
        """List files."""
        files: list[StoredFile] = await self._call_cloud_api(
            path=f"/files/{storage_type}"
        )
        return files

    @api_exception_handler(FilesError)
    async def delete(
        self,
        storage_type: StorageType,
        filename: str,
    ) -> None:
        """Delete a file."""
        _LOGGER.debug("Deleting %s file with name %s", storage_type, filename)
        await self._call_cloud_api(
            path="/files",
            method="DELETE",
            jsondata={
                "storage_type": storage_type,
                "filename": filename,
            },
        )
