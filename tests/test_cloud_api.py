"""Test cloud API."""


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
