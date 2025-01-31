"""Tests for Files."""

from typing import Any
from unittest.mock import AsyncMock

from aiohttp import ClientError
import pytest

from hass_nabucasa import Cloud
from hass_nabucasa.files import Files, FilesError
from tests.utils.aiohttp import AiohttpClientMocker

API_HOSTNAME = "example.com"
FILES_API_URL = "https://files.api.fakeurl/path?X-Amz-Algorithm=blah"


STORED_BACKUP = {
    "Key": "backup.tar",
    "Size": 1024,
    "LastModified": "2021-07-01T12:00:00Z",
    "Metadata": {"beer": "me"},
}


@pytest.fixture(autouse=True)
def set_hostname(auth_cloud_mock: Cloud):
    """Set API hostname for the mock cloud service."""
    auth_cloud_mock.servicehandlers_server = API_HOSTNAME


@pytest.mark.parametrize(
    "exception,msg",
    [
        [TimeoutError, "Timeout reached while calling API"],
        [ClientError, "Failed to fetch"],
        [Exception, "Unexpected error while calling API"],
    ],
)
async def test_upload_exceptions_while_getting_details(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    msg: str,
):
    """Test handling exceptions when fetching upload details."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/upload_details",
        exc=exception("Boom!"),
    )

    with pytest.raises(FilesError, match=msg):
        await files.upload(
            storage_type="test",
            open_stream=AsyncMock(),
            filename="lorem.ipsum",
            base64md5hash="hash",
            size=1337,
            metadata={"awesome": True},
        )


@pytest.mark.parametrize(
    "exception,msg",
    [
        [TimeoutError, "Timeout reached while trying to upload file"],
        [ClientError, "Failed to upload file"],
        [Exception, "Unexpected error while uploading file"],
    ],
)
async def test_upload_exceptions_while_uploading(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    msg: str,
):
    """Test handling exceptions during file upload."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/upload_details",
        json={"url": FILES_API_URL, "headers": {}},
    )

    aioclient_mock.put(FILES_API_URL, exc=exception("Boom!"))

    with pytest.raises(FilesError, match=msg):
        await files.upload(
            storage_type="test",
            open_stream=AsyncMock(),
            filename="lorem.ipsum",
            base64md5hash="hash",
            size=1337,
            metadata={"awesome": True},
        )


@pytest.mark.parametrize(
    "exception,getmockargs,log_msg",
    [
        [
            FilesError,
            {"status": 400, "json": {"message": "NC-CE-03"}},
            "Response from example.com/files/upload_details (400) NC-CE-03",
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
            "Response from example.com/files/upload_details (500)",
        ],
    ],
)
async def test_upload_bad_status_while_getting_upload_details(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    getmockargs: dict[str, Any],
    log_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test handling bad status codes when fetching upload details."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/upload_details",
        **getmockargs,
    )

    with pytest.raises(exception):
        await files.upload(
            storage_type="test",
            open_stream=AsyncMock(),
            filename="lorem.ipsum",
            base64md5hash="hash",
            size=1337,
            metadata={"awesome": True},
        )

    assert log_msg in caplog.text


@pytest.mark.parametrize(
    "exception,putmockargs,log_msg",
    [
        [
            FilesError,
            {"status": 400, "json": {"message": "Oh no!"}},
            "Response from files.api.fakeurl (400)",
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
            "Response from files.api.fakeurl (500)",
        ],
    ],
)
async def test_upload_bad_status_while_uploading(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    putmockargs: dict[str, Any],
    log_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test handling bad status codes during file upload."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/upload_details",
        json={"url": FILES_API_URL, "headers": {}},
    )

    aioclient_mock.put(FILES_API_URL, **putmockargs)

    with pytest.raises(exception):
        await files.upload(
            storage_type="test",
            open_stream=AsyncMock(),
            filename="lorem.ipsum",
            base64md5hash="hash",
            size=1337,
            metadata={"awesome": True},
        )

    assert log_msg in caplog.text


async def test_upload(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test successful file upload."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/upload_details",
        json={"url": FILES_API_URL, "headers": {}},
    )

    aioclient_mock.put(FILES_API_URL, status=200)

    await files.upload(
        storage_type="test",
        open_stream=AsyncMock(),
        filename="lorem.ipsum",
        base64md5hash="hash",
        size=1337,
        metadata={"awesome": True},
    )

    assert "Uploading file lorem.ipsum" in caplog.text
    assert "Response from example.com/files/upload_details (200)" in caplog.text
    assert "Response from files.api.fakeurl (200)" in caplog.text


@pytest.mark.parametrize(
    "exception,msg",
    [
        [TimeoutError, "Timeout reached while calling API"],
        [ClientError, "Failed to fetch"],
        [Exception, "Unexpected error while calling API"],
    ],
)
async def test_download_exceptions_while_getting_details(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    msg: str,
):
    """Test handling exceptions when fetching download details."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/download_details/test/lorem.ipsum",
        exc=exception("Boom!"),
    )

    with pytest.raises(FilesError, match=msg):
        await files.download(
            storage_type="test",
            filename="lorem.ipsum",
        )


@pytest.mark.parametrize(
    "exception,msg",
    [
        [TimeoutError, "Timeout reached while trying to download file"],
        [ClientError, "Failed to download file"],
        [Exception, "Unexpected error while downloading file"],
    ],
)
async def test_upload_exceptions_while_downloading(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    msg: str,
):
    """Test handling exceptions during file download."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/download_details/test/lorem.ipsum",
        json={"url": FILES_API_URL},
    )

    aioclient_mock.get(FILES_API_URL, exc=exception("Boom!"))

    with pytest.raises(FilesError, match=msg):
        await files.download(
            storage_type="test",
            filename="lorem.ipsum",
        )


@pytest.mark.parametrize(
    "exception,getmockargs,log_msg",
    [
        [
            FilesError,
            {"status": 400, "json": {"message": "NC-CE-03"}},
            "Response from example.com/files/download_details/test/lorem.ipsum "
            "(400) NC-CE-03",
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
            "Response from example.com/files/download_details/test/lorem.ipsum (500)",
        ],
    ],
)
async def test_upload_bad_status_while_getting_download_details(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    getmockargs: dict[str, Any],
    log_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test handling bad status codes when fetching download details."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/download_details/test/lorem.ipsum",
        **getmockargs,
    )

    with pytest.raises(exception):
        await files.download(
            storage_type="test",
            filename="lorem.ipsum",
        )

    assert log_msg in caplog.text


@pytest.mark.parametrize(
    "exception,getmockargs,log_msg",
    [
        [
            FilesError,
            {"status": 400, "json": {"message": "Oh no!"}},
            "Response from files.api.fakeurl (400)",
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
            "Response from files.api.fakeurl (500)",
        ],
    ],
)
async def test_upload_bad_status_while_downloading(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    getmockargs: dict[str, Any],
    log_msg: str,
    caplog: pytest.LogCaptureFixture,
):
    """Test handling bad status codes during file download."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/download_details/test/lorem.ipsum",
        json={"url": FILES_API_URL},
    )

    aioclient_mock.get(FILES_API_URL, **getmockargs)

    with pytest.raises(exception):
        await files.download(
            storage_type="test",
            filename="lorem.ipsum",
        )

    assert log_msg in caplog.text


async def test_downlaod(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test successful file download."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/download_details/test/lorem.ipsum",
        json={"url": FILES_API_URL},
    )

    aioclient_mock.get(FILES_API_URL, status=200)

    await files.download(
        storage_type="test",
        filename="lorem.ipsum",
    )
    assert "Downloading file lorem.ipsum" in caplog.text
    assert (
        "Response from example.com/files/download_details/test/lorem.ipsum (200)"
        in caplog.text
    )
    assert "Response from files.api.fakeurl (200)" in caplog.text
