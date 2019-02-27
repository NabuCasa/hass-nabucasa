"""Test cloud API."""
from unittest.mock import Mock, patch

import pytest

from hass_nabucasa import cloud_api


@pytest.fixture(autouse=True)
def mock_check_token():
    """Mock check token."""
    with patch("hass_nabucasa.auth_api." "check_token"):
        yield


async def test_create_cloudhook(cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post(
        "https://example.com/bla",
        json={"cloudhook_id": "mock-webhook", "url": "https://blabla"},
    )
    cloud_mock.id_token = "mock-id-token"
    cloud_mock.cloudhook_create_url = "https://example.com/bla"

    resp = await cloud_api.async_create_cloudhook(cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1
    assert await resp.json() == {
        "cloudhook_id": "mock-webhook",
        "url": "https://blabla",
    }


async def test_remote_register(cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post(
        "https://example.com/bla/register_instance",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    cloud_mock.id_token = "mock-id-token"
    cloud_mock.remote_api_url = "https://example.com/bla"

    resp = await cloud_api.async_remote_register(cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1
    assert await resp.json() == {
        "domain": "test.dui.nabu.casa",
        "email": "test@nabucasa.inc",
        "server": "rest-remote.nabu.casa",
    }


async def test_remote_token(cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post(
        "https://example.com/bla/snitun_token",
        json={"token": "123456", "server": "rest-remote.nabu.casa"},
    )
    cloud_mock.id_token = "mock-id-token"
    cloud_mock.remote_api_url = "https://example.com/bla"

    resp = await cloud_api.async_remote_token(cloud_mock, b"aes", b"iv")
    assert len(aioclient_mock.mock_calls) == 1
    assert await resp.json() == {"token": "123456", "server": "rest-remote.nabu.casa"}
    assert aioclient_mock.mock_calls[0][2] == {"aes_iv": "6976", "aes_key": "616573"}


async def test_remote_challenge(cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post("https://example.com/bla/challenge_txt")
    cloud_mock.id_token = "mock-id-token"
    cloud_mock.remote_api_url = "https://example.com/bla"

    resp = await cloud_api.async_remote_challenge(cloud_mock, "123456")
    assert len(aioclient_mock.mock_calls) == 1
    assert aioclient_mock.mock_calls[0][2] == {"txt": "123456"}
