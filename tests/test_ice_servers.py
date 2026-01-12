"""Test the ICE servers module."""

import asyncio
import time

import pytest

from hass_nabucasa import ice_servers
from tests.utils.aiohttp import AiohttpClientMocker


@pytest.fixture
def ice_servers_api(auth_cloud_mock) -> ice_servers.IceServers:
    """ICE servers API fixture."""
    auth_cloud_mock.servicehandlers_server = "example.com"
    auth_cloud_mock.id_token = "mock-id-token"
    return ice_servers.IceServers(auth_cloud_mock)


@pytest.fixture
def mock_ice_servers(aioclient_mock: AiohttpClientMocker):
    """Mock ICE servers."""
    aioclient_mock.get(
        "https://example.com/v2/webrtc/ice_servers",
        json=[
            {
                "urls": "stun:example.com:80",
            },
            {
                "urls": "turn:example.com:80",
                "username": "some-user",
                "credential": "secret-value",
                "ttl": 3600,
            },
        ],
    )


async def test_async_start_fetches_and_ice_servers_returns(
    ice_servers_api: ice_servers.IceServers,
    mock_ice_servers,
):
    """Test that async_start fetches and ice_servers returns ICE servers."""
    await ice_servers_api.async_start()
    result = ice_servers_api.ice_servers

    assert len(result) == 2
    assert result[0].urls == "stun:example.com:80"
    assert result[0].username is None
    assert result[0].credential is None
    assert result[1].urls == "turn:example.com:80"
    assert result[1].username == "some-user"
    assert result[1].credential == "secret-value"

    # Internal state should be populated
    assert len(ice_servers_api._nabucasa_ice_servers) == 2
    assert (
        ice_servers_api._nabucasa_ice_servers[1].expiration_timestamp
        == int(time.time()) + 3600
    )

    # Refresh task should be running
    assert ice_servers_api._refresh_task is not None
    assert not ice_servers_api._refresh_task.done()

    # Clean up
    ice_servers_api._refresh_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await ice_servers_api._refresh_task


async def test_async_start_triggers_periodic_update(
    ice_servers_api: ice_servers.IceServers,
    mock_ice_servers,
    aioclient_mock: AiohttpClientMocker,
):
    """Test that async_start triggers periodic ICE server updates."""
    ice_servers_api._get_refresh_sleep_time = lambda: 0

    await ice_servers_api.async_start()
    result = ice_servers_api.ice_servers
    assert len(result) == 2

    # Let the periodic update run a few times
    await asyncio.sleep(0.01)
    await asyncio.sleep(0.01)

    # Should have made multiple API calls due to periodic refresh
    assert len(aioclient_mock.mock_calls) >= 2

    # Clean up
    ice_servers_api._refresh_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await ice_servers_api._refresh_task


async def test_async_stop_cancels_refresh_task(
    ice_servers_api: ice_servers.IceServers,
    mock_ice_servers,
):
    """Test that async_stop cancels the refresh task and clears state."""
    # Start the refresh task by getting ice servers
    await ice_servers_api.async_start()
    result = ice_servers_api.ice_servers
    assert len(result) == 2
    assert ice_servers_api._refresh_task is not None
    assert not ice_servers_api._refresh_task.done()

    # Stop the refresh task
    await ice_servers_api.async_stop()

    # Verify state is cleared
    assert ice_servers_api._refresh_task is None
    assert ice_servers_api._nabucasa_ice_servers == []
    assert ice_servers_api._initial_fetch_event is None


async def test_async_stop_when_not_started(
    ice_servers_api: ice_servers.IceServers,
):
    """Test that async_stop works when no task is running."""
    # Should not raise any errors
    await ice_servers_api.async_stop()

    assert ice_servers_api._refresh_task is None
    assert ice_servers_api._nabucasa_ice_servers == []


async def test_async_start_returns_empty_on_expired_subscription(
    ice_servers_api: ice_servers.IceServers,
    aioclient_mock: AiohttpClientMocker,
):
    """Test that async_start returns empty list when subscription expired."""
    ice_servers_api._cloud.subscription_expired = True

    await ice_servers_api.async_start()
    result = ice_servers_api.ice_servers

    assert result == []
    assert len(aioclient_mock.mock_calls) == 0
    # No task should be created for expired subscription
    assert ice_servers_api._refresh_task is None


async def test_ice_server_refresh_sets_ice_server_list_empty_on_401_403_client_error(
    ice_servers_api: ice_servers.IceServers,
    aioclient_mock: AiohttpClientMocker,
):
    """Test that ICE server list is empty when server returns 401 or 403 errors."""
    aioclient_mock.get(
        "https://example.com/v2/webrtc/ice_servers",
        status=403,
        json={"message": "Boom!"},
    )

    ice_servers_api._get_refresh_sleep_time = lambda: 0

    # Pre-populate with servers
    ice_servers_api._nabucasa_ice_servers = [
        ice_servers.NabucasaIceServer(
            {"urls": "stun:example.com:80"},
        ),
        ice_servers.NabucasaIceServer(
            {
                "urls": "turn:example.com:80",
                "username": "some-user",
                "credential": "secret-value",
                "ttl": 3600,
            },
        ),
    ]

    # Getting servers should trigger refresh which will fail
    await ice_servers_api.async_start()
    result = ice_servers_api.ice_servers

    # Servers should be cleared on 403
    assert result == []
    assert ice_servers_api._nabucasa_ice_servers == []

    # Clean up
    ice_servers_api._refresh_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await ice_servers_api._refresh_task


async def test_ice_server_refresh_keeps_ice_server_list_on_other_client_errors(
    ice_servers_api: ice_servers.IceServers,
    aioclient_mock,
):
    """Test that ICE server list is not set to empty when server returns an error."""
    aioclient_mock.get(
        "https://example.com/v2/webrtc/ice_servers",
        status=500,
        json={"message": "Boom!"},
    )

    ice_servers_api._get_refresh_sleep_time = lambda: 0

    # Pre-populate with servers
    ice_servers_api._nabucasa_ice_servers = [
        ice_servers.NabucasaIceServer(
            {"urls": "stun:example.com:80"},
        ),
        ice_servers.NabucasaIceServer(
            {
                "urls": "turn:example.com:80",
                "username": "some-user",
                "credential": "secret-value",
                "ttl": 3600,
            },
        ),
    ]

    # Getting servers should trigger refresh which will fail
    await ice_servers_api.async_start()
    result = ice_servers_api.ice_servers

    # Servers should be kept on 500 error
    assert len(result) == 2
    assert len(ice_servers_api._nabucasa_ice_servers) == 2

    # Clean up
    ice_servers_api._refresh_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await ice_servers_api._refresh_task


def test_get_refresh_sleep_time(ice_servers_api: ice_servers.IceServers):
    """Test get refresh sleep time."""
    min_timestamp = 86400

    ice_servers_api._nabucasa_ice_servers = [
        ice_servers.NabucasaIceServer(
            {
                "urls": "turn:example.com:80",
                "username": "some-user",
                "credential": "secret-value",
                "ttl": 9999999999,
            }
        ),
        ice_servers.NabucasaIceServer(
            {
                "urls": "turn:example.com:80",
                "username": "some-user",
                "credential": "secret-value",
                "ttl": min_timestamp,
            }
        ),
    ]

    assert ice_servers_api._get_refresh_sleep_time() == min_timestamp - 3600


def test_get_refresh_sleep_time_no_turn_servers(
    ice_servers_api: ice_servers.IceServers,
):
    """Test get refresh sleep time."""
    refresh_time = ice_servers_api._get_refresh_sleep_time()

    assert refresh_time >= 3600
    assert refresh_time <= 43200


def test_get_refresh_sleep_time_expiration_less_than_one_hour(
    ice_servers_api: ice_servers.IceServers,
):
    """Test get refresh sleep time."""
    min_timestamp = 10

    ice_servers_api._nabucasa_ice_servers = [
        ice_servers.NabucasaIceServer(
            {
                "urls": "turn:example.com:80",
                "username": "some-user",
                "credential": "secret-value",
                "ttl": 9999999999,
            }
        ),
        ice_servers.NabucasaIceServer(
            {
                "urls": "turn:example.com:80",
                "username": "some-user",
                "credential": "secret-value",
                "ttl": min_timestamp,
            }
        ),
    ]

    refresh_time = ice_servers_api._get_refresh_sleep_time()

    assert refresh_time >= 100
    assert refresh_time <= 300
