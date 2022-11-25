"""Test cloud API."""
from unittest.mock import patch, AsyncMock

from hass_nabucasa import cloud_api


async def test_create_cloudhook(auth_cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post(
        "https://example.com/bla",
        json={"cloudhook_id": "mock-webhook", "url": "https://blabla"},
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.cloudhook_create_url = "https://example.com/bla"

    resp = await cloud_api.async_create_cloudhook(auth_cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1
    assert await resp.json() == {
        "cloudhook_id": "mock-webhook",
        "url": "https://blabla",
    }


async def test_remote_register(auth_cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post(
        "https://example.com/bla/register_instance",
        json={
            "domain": "test.dui.nabu.casa",
            "email": "test@nabucasa.inc",
            "server": "rest-remote.nabu.casa",
        },
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.remote_api_url = "https://example.com/bla"

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
        "https://example.com/bla/snitun_token",
        json={
            "token": "123456",
            "server": "rest-remote.nabu.casa",
            "valid": 12345,
            "throttling": 400,
        },
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.remote_api_url = "https://example.com/bla"

    resp = await cloud_api.async_remote_token(auth_cloud_mock, b"aes", b"iv")
    assert len(aioclient_mock.mock_calls) == 1
    assert await resp.json() == {
        "token": "123456",
        "server": "rest-remote.nabu.casa",
        "valid": 12345,
        "throttling": 400,
    }
    assert aioclient_mock.mock_calls[0][2] == {"aes_iv": "6976", "aes_key": "616573"}


async def test_remote_challenge_txt(auth_cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post("https://example.com/bla/challenge_txt")
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.remote_api_url = "https://example.com/bla"

    await cloud_api.async_remote_challenge_txt(auth_cloud_mock, "123456")
    assert len(aioclient_mock.mock_calls) == 1
    assert aioclient_mock.mock_calls[0][2] == {"txt": "123456"}


async def test_remote_challenge_cleanup(auth_cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post("https://example.com/bla/challenge_cleanup")
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.remote_api_url = "https://example.com/bla"

    await cloud_api.async_remote_challenge_cleanup(auth_cloud_mock, "123456")
    assert len(aioclient_mock.mock_calls) == 1
    assert aioclient_mock.mock_calls[0][2] == {"txt": "123456"}


async def test_get_access_token(auth_cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.post("https://example.com/bla")
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.alexa_access_token_url = "https://example.com/bla"

    await cloud_api.async_alexa_access_token(auth_cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1


async def test_voice_connection_details(auth_cloud_mock, aioclient_mock):
    """Test creating a cloudhook."""
    aioclient_mock.get("https://example.com/connection_details")
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.voice_api_url = "https://example.com"

    await cloud_api.async_voice_connection_details(auth_cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1


async def test_subscription_info(auth_cloud_mock, aioclient_mock):
    """Test fetching subscription info."""
    aioclient_mock.get(
        "https://example.com/payments/subscription_info",
        json={
            "success": True,
            "provider": None,
        },
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.subscription_info_url = (
        "https://example.com/payments/subscription_info"
    )

    with patch.object(
        auth_cloud_mock.auth, "async_renew_access_token", AsyncMock()
    ) as mock_renew:
        data = await cloud_api.async_subscription_info(auth_cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1
    assert data == {
        "success": True,
        "provider": None,
    }

    auth_cloud_mock.started = False
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        "https://example.com/payments/subscription_info",
        json={
            "success": True,
            "provider": "mock-provider",
        },
    )
    with patch.object(
        auth_cloud_mock.auth, "async_renew_access_token", AsyncMock()
    ) as mock_renew:
        data = await cloud_api.async_subscription_info(auth_cloud_mock)

    assert len(aioclient_mock.mock_calls) == 1
    assert data == {
        "success": True,
        "provider": "mock-provider",
    }
    assert len(mock_renew.mock_calls) == 1


async def test_migrate_subscription(auth_cloud_mock, aioclient_mock):
    """Test migrating a subscription."""
    aioclient_mock.post(
        "https://example.com/migrate_paypal_agreement",
        json={
            "url": "https://example.com/some/path",
        },
    )
    auth_cloud_mock.id_token = "mock-id-token"
    auth_cloud_mock.migrate_subscription_url = (
        "https://example.com/migrate_paypal_agreement"
    )

    data = await cloud_api.async_migrate_subscription(auth_cloud_mock)
    assert len(aioclient_mock.mock_calls) == 1
    assert data == {
        "url": "https://example.com/some/path",
    }
