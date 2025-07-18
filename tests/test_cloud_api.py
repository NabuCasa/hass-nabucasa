"""Test cloud API."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

from aiohttp import ClientResponseError
import pytest

from hass_nabucasa import cloud_api
from tests.utils.aiohttp import AiohttpClientMocker


async def test_create_cloudhook(auth_cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post(
        "https://example.com/generate",
        json={"cloudhook_id": "mock-webhook", "url": "https://blabla"},
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.cloudhook_server = "example.com"

    resp = await cloud_api.async_create_cloudhook(auth_cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1
    assert await resp.json() == {
        "cloudhook_id": "mock-webhook",
        "url": "https://blabla",
    }


async def test_remote_register(auth_cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post(
        "https://example.com/bla/instance/register",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.servicehandlers_server = "example.com/bla"

    resp = await cloud_api.async_remote_register(auth_cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1
    assert await resp.json() == {
        "domain": "test.dui.nabu.casa",
        "email": "test@nabucasa.inc",
        "server": "rest-remote.nabu.casa",
    }


async def test_remote_token(auth_cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post(
        "https://example.com/instance/snitun_token",
        json={
            "token": "123456",
            "server": "rest-remote.nabu.casa",
            "valid": 12345,
            "throttling": 400,
        },
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.servicehandlers_server = "example.com"

    resp = await cloud_api.async_remote_token(auth_cloud_mock, b"aes", b"iv")
    assert len(aioclient_mock.mock_calls) == 1
    assert await resp.json() == {
        "token": "123456",
        "server": "rest-remote.nabu.casa",
        "valid": 12345,
        "throttling": 400,
    }
    assert aioclient_mock.mock_calls[0][2] == {"aes_iv": "6976", "aes_key": "616573"}


async def test_get_access_token(auth_cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post("https://example.com/alexa/access_token")
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.servicehandlers_server = "example.com"

    await cloud_api.async_alexa_access_token(auth_cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1


async def test_migrate_paypal_agreement(auth_cloud_mock, aioclient_mock):
    """Test a paypal agreement from legacy."""
    aioclient_mock.post(
        "https://example.com/payments/migrate_paypal_agreement",
        json={
            "url": "https://example.com/some/path",
        },
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.accounts_server = "example.com"

    data = await cloud_api.async_migrate_paypal_agreement(auth_cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1
    assert data == {
        "url": "https://example.com/some/path",
    }


async def test_async_files_download_details(
    auth_cloud_mock: MagicMock,
    aioclient_mock: Generator[AiohttpClientMocker, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test the async_files_download_details function."""
    aioclient_mock.get(
        "https://example.com/files/download_details/test/test.txt",
        json={
            "url": "https://example.com/some/path",
        },
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.servicehandlers_server = "example.com"

    details = await cloud_api.async_files_download_details(
        cloud=auth_cloud_mock,
        storage_type="test",
        filename="test.txt",
    )

    assert len(aioclient_mock.mock_calls) == 1
    assert details == {
        "url": "https://example.com/some/path",
    }
    assert (
        "Fetched https://example.com/files/download_details/test/test.txt (200)"
        in caplog.text
    )


async def test_async_files_download_details_error(
    auth_cloud_mock: MagicMock,
    aioclient_mock: Generator[AiohttpClientMocker, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test the async_files_download_details function with error."""
    aioclient_mock.get(
        "https://example.com/files/download_details/test/test.txt",
        status=400,
        json={"message": "Boom!"},
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.servicehandlers_server = "example.com"

    with pytest.raises(ClientResponseError):
        await cloud_api.async_files_download_details(
            cloud=auth_cloud_mock,
            storage_type="test",
            filename="test.txt",
        )

    assert len(aioclient_mock.mock_calls) == 1
    assert (
        "Fetched https://example.com/files/download_details/test/test.txt (400) Boom!"
        in caplog.text
    )


async def test_async_files_list(
    auth_cloud_mock: MagicMock,
    aioclient_mock: Generator[AiohttpClientMocker, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test the async_files_list function."""
    aioclient_mock.get(
        "https://example.com/files/test",
        json=[{"Key": "test.txt", "LastModified": "2021-01-01T00:00:00Z", "Size": 2}],
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.servicehandlers_server = "example.com"

    details = await cloud_api.async_files_list(
        cloud=auth_cloud_mock,
        storage_type="test",
    )

    assert len(aioclient_mock.mock_calls) == 1
    assert details == [
        {
            "Key": "test.txt",
            "LastModified": "2021-01-01T00:00:00Z",
            "Size": 2,
        },
    ]
    assert "Fetched https://example.com/files/test (200)" in caplog.text


async def test_async_files_list_error(
    auth_cloud_mock: MagicMock,
    aioclient_mock: Generator[AiohttpClientMocker, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test the async_files_list function with error listing files."""
    aioclient_mock.get(
        "https://example.com/files/test",
        status=400,
        json={"message": "Boom!"},
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.servicehandlers_server = "example.com"

    with pytest.raises(ClientResponseError):
        await cloud_api.async_files_list(
            cloud=auth_cloud_mock,
            storage_type="test",
        )

    assert len(aioclient_mock.mock_calls) == 1

    assert "Fetched https://example.com/files/test (400) Boom!" in caplog.text


async def test_async_files_upload_details(
    auth_cloud_mock: MagicMock,
    aioclient_mock: Generator[AiohttpClientMocker, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test the async_files_upload_details function."""
    aioclient_mock.get(
        "https://example.com/files/upload_details",
        json={
            "url": "https://example.com/some/path",
            "headers": {"key": "value"},
        },
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.servicehandlers_server = "example.com"

    base64md5hash = "dGVzdA=="

    details = await cloud_api.async_files_upload_details(
        cloud=auth_cloud_mock,
        storage_type="test",
        filename="test.txt",
        base64md5hash=base64md5hash,
        size=2,
        metadata={"homeassistant_version": "1970.1.1"},
    )

    assert len(aioclient_mock.mock_calls) == 1
    # 2 is the body
    assert aioclient_mock.mock_calls[0][2] == {
        "filename": "test.txt",
        "storage_type": "test",
        "metadata": {"homeassistant_version": "1970.1.1"},
        "md5": base64md5hash,
        "size": 2,
    }

    assert details == {
        "url": "https://example.com/some/path",
        "headers": {"key": "value"},
    }
    assert "Fetched https://example.com/files/upload_details (200)" in caplog.text


async def test_async_files_upload_details_error(
    auth_cloud_mock: MagicMock,
    aioclient_mock: Generator[AiohttpClientMocker, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test the async_files_upload_details function with error generating upload URL."""
    aioclient_mock.get(
        "https://example.com/files/upload_details",
        status=400,
        json={"message": "Boom!"},
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.servicehandlers_server = "example.com"

    base64md5hash = "dGVzdA=="

    with pytest.raises(ClientResponseError):
        await cloud_api.async_files_upload_details(
            cloud=auth_cloud_mock,
            storage_type="test",
            filename="test.txt",
            base64md5hash=base64md5hash,
            size=2,
        )

    assert len(aioclient_mock.mock_calls) == 1
    # 2 is the body
    assert aioclient_mock.mock_calls[0][2] == {
        "filename": "test.txt",
        "storage_type": "test",
        "md5": base64md5hash,
        "size": 2,
        "metadata": None,
    }

    assert "Fetched https://example.com/files/upload_details (400) Boom!" in caplog.text


async def test_async_files_delete_file(
    auth_cloud_mock: MagicMock,
    aioclient_mock: Generator[AiohttpClientMocker, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test the async_files_delete_file function."""
    aioclient_mock.delete(
        "https://example.com/files",
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.servicehandlers_server = "example.com"

    await cloud_api.async_files_delete_file(
        cloud=auth_cloud_mock,
        storage_type="test",
        filename="test.txt",
    )

    assert len(aioclient_mock.mock_calls) == 1
    # 2 is the body
    assert aioclient_mock.mock_calls[0][2] == {
        "filename": "test.txt",
        "storage_type": "test",
    }

    assert "Fetched https://example.com/files (200)" in caplog.text


async def test_async_files_delete_file_error(
    auth_cloud_mock: MagicMock,
    aioclient_mock: Generator[AiohttpClientMocker, Any],
    caplog: pytest.LogCaptureFixture,
):
    """Test the async_files_delete_file function with error."""
    aioclient_mock.delete(
        "https://example.com/files",
        status=400,
        json={"message": "Boom!"},
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.servicehandlers_server = "example.com"

    with pytest.raises(ClientResponseError):
        await cloud_api.async_files_delete_file(
            cloud=auth_cloud_mock,
            storage_type="test",
            filename="test.txt",
        )

    assert len(aioclient_mock.mock_calls) == 1
    # 2 is the body
    assert aioclient_mock.mock_calls[0][2] == {
        "filename": "test.txt",
        "storage_type": "test",
    }

    assert "Fetched https://example.com/files (400) Boom!" in caplog.text
