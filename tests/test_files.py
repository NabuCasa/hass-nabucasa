"""Tests for Files."""

from collections.abc import AsyncIterator, Iterable
import re
from typing import Any
from unittest.mock import AsyncMock

from aiohttp import ClientError
import pytest

from hass_nabucasa import Cloud
from hass_nabucasa.api import CloudApiNonRetryableError
from hass_nabucasa.files import Files, FilesError, calculate_b64md5
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
    "putmockargs,msg",
    [
        [{"exc": TimeoutError("Boom!")}, "Timeout reached while calling API"],
        [{"exc": ClientError("Boom!")}, "Failed to fetch: Boom!"],
        [{"exc": Exception("Boom!")}, "Unexpected error while calling API: Boom!"],
        [{"status": 400}, "Failed to upload: (400) "],
        [
            {"status": 400, "text": "Unknown error structure"},
            "Failed to upload: (400) Unknown error structure",
        ],
        [
            {
                "status": 400,
                "text": "<Message>Pretty error\nWith a linebreak</Message>",
            },
            "Failed to upload: (400) Pretty error With a linebreak",
        ],
        [
            {
                "status": 400,
                "text": "<Message>What is this?",
            },
            "Failed to upload: (400) <Message>What is this?",
        ],
        [
            {
                "status": 400,
                "text": f"{'a' * 512}",
            },
            f"Failed to upload: (400) {'a' * 256}",
        ],
        [
            {
                "status": 403,
                "text": "<Message>Pretty error\nWith a linebreak</Message>",
            },
            "Failed to upload: (403) Pretty error With a linebreak",
        ],
        [
            {
                "status": 500,
                "text": "<Message>Pretty error\nWith a linebreak</Message>",
            },
            "Failed to upload: (500) ",
        ],
    ],
)
async def test_upload_exceptions_while_uploading(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    putmockargs: dict[str, Any],
    msg: str,
):
    """Test handling exceptions during file upload."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/upload_details",
        json={"url": FILES_API_URL, "headers": {}},
    )

    aioclient_mock.put(FILES_API_URL, **putmockargs)

    with pytest.raises(FilesError, match=f"^{re.escape(msg)}$"):
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
            {"status": 400, "json": {"message": "NC-CE-01"}},
            "Response for get from example.com/files/upload_details (400) NC-CE-01",
        ],
        [
            CloudApiNonRetryableError,
            {"status": 400, "json": {"message": "NC-CE-03"}},
            "Response for get from example.com/files/upload_details (400) NC-CE-03",
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for get from example.com/files/upload_details (500)",
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


async def test_upload_returning_403_and_expired_subscription(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test handling 403 when the subscription is expired."""
    auth_cloud_mock.subscription_expired = True
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/upload_details",
        status=403,
        json={"message": "Forbidden"},
    )

    with pytest.raises(CloudApiNonRetryableError, match="Subscription has expired"):
        await files.upload(
            storage_type="test",
            open_stream=AsyncMock(),
            filename="lorem.ipsum",
            base64md5hash="hash",
            size=1337,
            metadata={"awesome": True},
        )

    assert (
        "Response for get from example.com/files/upload_details (403) Forbidden"
        in caplog.text
    )


@pytest.mark.parametrize(
    "exception,putmockargs,log_msg",
    [
        [
            FilesError,
            {"status": 400, "json": {"message": "Oh no!"}},
            "Response for put from files.api.fakeurl (400)",
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for put from files.api.fakeurl (500)",
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

    assert "Uploading test file with name lorem.ipsum" in caplog.text
    assert "Response for get from example.com/files/upload_details (200)" in caplog.text
    assert "Response for put from files.api.fakeurl (200)" in caplog.text


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
        [TimeoutError, "Timeout reached while calling API"],
        [ClientError, "Failed to fetch"],
        [Exception, "Unexpected error while calling API"],
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
            CloudApiNonRetryableError,
            {"status": 400, "json": {"message": "NC-SH-FH-03 (abc-123)"}},
            "Response for get from example.com/files/download_details/test/lorem.ipsum "
            "(400) NC-SH-FH-03 (abc-123)",
        ],
        [
            CloudApiNonRetryableError,
            {"status": 400, "json": {"message": "NC-CE-03"}},
            "Response for get from example.com/files/download_details/test/lorem.ipsum "
            "(400) NC-CE-03",
        ],
        [
            FilesError,
            {"status": 400, "json": {"message": "NC-CE-01"}},
            "Response for get from example.com/files/download_details/test/lorem.ipsum "
            "(400) NC-CE-01",
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for get from example.com/files/download_details/test/lorem.ipsum"
            " (500)",
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
            "Response for get from files.api.fakeurl (400)",
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
            "Response for get from files.api.fakeurl (500)",
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
    assert "Downloading test file with name lorem.ipsum" in caplog.text
    assert len(aioclient_mock.mock_calls) == 2
    assert (
        "Response for get from example.com/files/download_details/test/lorem.ipsum "
        "(200)" in caplog.text
    )
    assert "Response for get from files.api.fakeurl (200)" in caplog.text


async def test_list(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test listing files."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(
        f"https://{API_HOSTNAME}/files/test",
        json=[STORED_BACKUP],
    )

    files = await files.list(storage_type="test")

    assert files[0] == STORED_BACKUP
    assert len(aioclient_mock.mock_calls) == 1
    assert "Response for get from example.com/files/test (200)" in caplog.text


@pytest.mark.parametrize(
    "exception,msg",
    [
        [TimeoutError, "Timeout reached while calling API"],
        [ClientError, "Failed to fetch"],
        [Exception, "Unexpected error while calling API"],
    ],
)
async def test_exceptions_while_listing(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception: Exception,
    msg: str,
):
    """Test handling exceptions during file download."""
    files = Files(auth_cloud_mock)
    aioclient_mock.get(f"https://{API_HOSTNAME}/files/test", exc=exception("Boom!"))

    with pytest.raises(FilesError, match=msg):
        await files.list(storage_type="test")

    assert len(aioclient_mock.mock_calls) == 1


async def test_delete(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test listing files."""
    files = Files(auth_cloud_mock)
    aioclient_mock.delete(f"https://{API_HOSTNAME}/files")

    await files.delete(storage_type="test", filename="lorem.ipsum")

    assert len(aioclient_mock.mock_calls) == 1
    assert aioclient_mock.mock_calls[0][2] == {
        "filename": "lorem.ipsum",
        "storage_type": "test",
    }
    assert "Deleting test file with name lorem.ipsum" in caplog.text
    assert "Response for delete from example.com/files (200)" in caplog.text


@pytest.mark.parametrize(
    "exception_msg,deletemockargs,log_msg",
    [
        [
            "Failed to fetch: (400) ",
            {"status": 400, "json": {"message": "NC-CE-01"}},
            "Response for delete from example.com/files (400) NC-CE-01",
        ],
        [
            "Failed to fetch: (500) ",
            {"status": 500, "text": "Internal Server Error"},
            "Response for delete from example.com/files (500)",
        ],
    ],
)
async def test_exceptions_while_deleting(
    aioclient_mock: AiohttpClientMocker,
    auth_cloud_mock: Cloud,
    exception_msg: str,
    log_msg: str,
    deletemockargs: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test handling exceptions during file download."""
    files = Files(auth_cloud_mock)
    aioclient_mock.delete(f"https://{API_HOSTNAME}/files", **deletemockargs)

    with pytest.raises(FilesError, match=re.escape(exception_msg)):
        await files.delete(storage_type="test", filename="lorem.ipsum")
    assert len(aioclient_mock.mock_calls) == 1
    assert log_msg in caplog.text


async def aiter_from_iter(iterable: Iterable) -> AsyncIterator:
    """Convert an iterable to an async iterator."""
    for i in iterable:
        yield i


async def test_calculate_b64md5():
    """Test calculating base64 md5 hash."""

    async def open_stream() -> AsyncIterator[bytes]:
        """Mock open stream."""
        return aiter_from_iter((b"backup", b"data"))

    assert await calculate_b64md5(open_stream, 10) == "p17gbFrsI2suQNBhkdO1Gw=="

    with pytest.raises(
        FilesError,
        match="Indicated size 9 does not match actual size 10",
    ):
        await calculate_b64md5(open_stream, 9)
