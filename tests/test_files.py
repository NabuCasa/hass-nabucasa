"""Tests for cloud.files."""

from collections.abc import AsyncIterator, Iterable
import re
from typing import Any
from unittest.mock import AsyncMock

from aiohttp import ClientError
import pytest
from syrupy import SnapshotAssertion

from hass_nabucasa import Cloud
from hass_nabucasa.api import CloudApiNonRetryableError
from hass_nabucasa.files import FilesError, calculate_b64md5
from tests.common import extract_log_messages
from tests.utils.aiohttp import AiohttpClientMocker

FILES_API_URL = "https://files.api.fakeurl/path?X-Amz-Algorithm=***"


STORED_BACKUP = {
    "Key": "backup.tar",
    "Size": 1024,
    "LastModified": "2021-07-01T12:00:00Z",
    "Metadata": {"beer": "me"},
}


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
    cloud: Cloud,
    exception: Exception,
    msg: str,
):
    """Test handling exceptions when fetching upload details."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/files/upload_details",
        exc=exception("Boom!"),
    )

    with pytest.raises(FilesError, match=msg):
        await cloud.files.upload(
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
        [
            {"exc": TimeoutError("Boom!")},
            "Timeout reached while calling API: total allowed time is 43200.0 seconds",
        ],
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
    cloud: Cloud,
    putmockargs: dict[str, Any],
    msg: str,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test handling exceptions during file upload."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/files/upload_details",
        json={"url": FILES_API_URL, "headers": {}},
    )

    aioclient_mock.put(FILES_API_URL, **putmockargs)

    with pytest.raises(FilesError, match=f"^{re.escape(msg)}$"):
        await cloud.files.upload(
            storage_type="test",
            open_stream=AsyncMock(),
            filename="lorem.ipsum",
            base64md5hash="hash",
            size=1337,
            metadata={"awesome": True},
        )
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.parametrize(
    "exception,getmockargs",
    [
        [
            FilesError,
            {"status": 400, "json": {"message": "NC-CE-01"}},
        ],
        [
            CloudApiNonRetryableError,
            {"status": 400, "json": {"message": "NC-CE-03"}},
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
        ],
    ],
)
async def test_upload_bad_status_while_getting_upload_details(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    getmockargs: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test handling bad status codes when fetching upload details."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/files/upload_details",
        **getmockargs,
    )

    with pytest.raises(exception):
        await cloud.files.upload(
            storage_type="test",
            open_stream=AsyncMock(),
            filename="lorem.ipsum",
            base64md5hash="hash",
            size=1337,
            metadata={"awesome": True},
        )

    assert extract_log_messages(caplog) == snapshot


async def test_upload_returning_403_and_expired_subscription(
    aioclient_mock: AiohttpClientMocker,
    cloud_with_expired_subscription: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test handling 403 when the subscription is expired."""
    cloud = cloud_with_expired_subscription

    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/files/upload_details",
        status=403,
        json={"message": "Forbidden"},
    )

    with pytest.raises(CloudApiNonRetryableError, match="Subscription has expired"):
        await cloud.files.upload(
            storage_type="test",
            open_stream=AsyncMock(),
            filename="lorem.ipsum",
            base64md5hash="hash",
            size=1337,
            metadata={"awesome": True},
        )

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.parametrize(
    "exception,putmockargs",
    [
        [
            FilesError,
            {"status": 400, "json": {"message": "Oh no!"}},
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
        ],
    ],
)
async def test_upload_bad_status_while_uploading(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    putmockargs: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test handling bad status codes during file upload."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/files/upload_details",
        json={"url": FILES_API_URL, "headers": {}},
    )

    aioclient_mock.put(FILES_API_URL, **putmockargs)

    with pytest.raises(exception):
        await cloud.files.upload(
            storage_type="test",
            open_stream=AsyncMock(),
            filename="lorem.ipsum",
            base64md5hash="hash",
            size=1337,
            metadata={"awesome": True},
        )

    assert extract_log_messages(caplog) == snapshot


async def test_upload(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test successful file upload."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/files/upload_details",
        json={"url": FILES_API_URL, "headers": {}},
    )
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/v2/files/test",
        json=[STORED_BACKUP],
    )

    aioclient_mock.put(FILES_API_URL, status=200)

    await cloud.files.upload(
        storage_type="test",
        open_stream=AsyncMock(),
        filename="lorem.ipsum",
        base64md5hash="hash",
        size=1337,
        metadata={"awesome": True},
    )

    assert extract_log_messages(caplog) == snapshot


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
    cloud: Cloud,
    exception: Exception,
    msg: str,
):
    """Test handling exceptions when fetching download details."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/files/download_details/test/lorem.ipsum",
        exc=exception("Boom!"),
    )

    with pytest.raises(FilesError, match=msg):
        await cloud.files.download(
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
    cloud: Cloud,
    exception: Exception,
    msg: str,
):
    """Test handling exceptions during file download."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/files/download_details/test/lorem.ipsum",
        json={"url": FILES_API_URL},
    )

    aioclient_mock.get(FILES_API_URL, exc=exception("Boom!"))

    with pytest.raises(FilesError, match=msg):
        await cloud.files.download(
            storage_type="test",
            filename="lorem.ipsum",
        )


@pytest.mark.parametrize(
    "exception,getmockargs",
    [
        [
            CloudApiNonRetryableError,
            {"status": 400, "json": {"message": "NC-SH-FH-03 (abc-123)"}},
        ],
        [
            CloudApiNonRetryableError,
            {"status": 400, "json": {"message": "NC-CE-03"}},
        ],
        [
            FilesError,
            {"status": 400, "json": {"message": "NC-CE-01"}},
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
        ],
    ],
)
async def test_upload_bad_status_while_getting_download_details(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    getmockargs: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test handling bad status codes when fetching download details."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/files/download_details/test/lorem.ipsum",
        **getmockargs,
    )

    with pytest.raises(exception):
        await cloud.files.download(
            storage_type="test",
            filename="lorem.ipsum",
        )

    assert extract_log_messages(caplog) == snapshot


@pytest.mark.parametrize(
    "exception,getmockargs",
    [
        [
            FilesError,
            {"status": 400, "json": {"message": "Oh no!"}},
        ],
        [
            FilesError,
            {"status": 500, "text": "Internal Server Error"},
        ],
    ],
)
async def test_upload_bad_status_while_downloading(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception: Exception,
    getmockargs: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test handling bad status codes during file download."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/files/download_details/test/lorem.ipsum",
        json={"url": FILES_API_URL},
    )

    aioclient_mock.get(FILES_API_URL, **getmockargs)

    with pytest.raises(exception):
        await cloud.files.download(
            storage_type="test",
            filename="lorem.ipsum",
        )

    assert extract_log_messages(caplog) == snapshot


async def test_download(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test successful file download."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/files/download_details/test/lorem.ipsum",
        json={"url": FILES_API_URL},
    )

    aioclient_mock.get(FILES_API_URL, status=200)

    await cloud.files.download(
        storage_type="test",
        filename="lorem.ipsum",
    )
    assert "Downloading test file with name lorem.ipsum" in caplog.text
    assert len(aioclient_mock.mock_calls) == 2
    assert extract_log_messages(caplog) == snapshot


async def test_list(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test listing cloud.files."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/v2/files/test",
        json=[STORED_BACKUP],
    )

    files = await cloud.files.list(storage_type="test")

    assert files[0] == STORED_BACKUP
    assert len(aioclient_mock.mock_calls) == 1
    assert extract_log_messages(caplog) == snapshot


async def test_list_with_clear_cache(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test listing cloud.files."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/v2/files/test?clearCache=true",
        json=[STORED_BACKUP],
    )

    files = await cloud.files.list(storage_type="test", clear_cache=True)

    assert files[0] == STORED_BACKUP
    assert len(aioclient_mock.mock_calls) == 1
    assert extract_log_messages(caplog) == snapshot


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
    cloud: Cloud,
    exception: Exception,
    msg: str,
):
    """Test handling exceptions during file download."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/v2/files/test", exc=exception("Boom!")
    )

    with pytest.raises(FilesError, match=msg):
        await cloud.files.list(storage_type="test")

    assert len(aioclient_mock.mock_calls) == 1


async def test_delete(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test listing cloud.files."""
    aioclient_mock.delete(f"https://{cloud.servicehandlers_server}/files")

    await cloud.files.delete(storage_type="test", filename="lorem.ipsum")

    assert len(aioclient_mock.mock_calls) == 1
    assert aioclient_mock.mock_calls[0][2] == {
        "filename": "lorem.ipsum",
        "storage_type": "test",
    }
    assert extract_log_messages(caplog) == snapshot


@pytest.mark.parametrize(
    "exception_msg,deletemockargs",
    [
        [
            "Failed to fetch: (400) ",
            {"status": 400, "json": {"message": "NC-CE-01"}},
        ],
        [
            "Failed to fetch: (500) ",
            {"status": 500, "text": "Internal Server Error"},
        ],
    ],
)
async def test_exceptions_while_deleting(
    aioclient_mock: AiohttpClientMocker,
    cloud: Cloud,
    exception_msg: str,
    deletemockargs: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test handling exceptions during file download."""
    aioclient_mock.delete(
        f"https://{cloud.servicehandlers_server}/files", **deletemockargs
    )

    with pytest.raises(FilesError, match=re.escape(exception_msg)):
        await cloud.files.delete(storage_type="test", filename="lorem.ipsum")
    assert len(aioclient_mock.mock_calls) == 1
    assert extract_log_messages(caplog) == snapshot


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
