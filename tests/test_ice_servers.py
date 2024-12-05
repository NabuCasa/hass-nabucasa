"""Test the ICE servers module."""

import asyncio
import time

import pytest
from webrtc_models import RTCIceServer

from hass_nabucasa import ice_servers
from tests.utils.aiohttp import AiohttpClientMocker


@pytest.fixture
def ice_servers_api(auth_cloud_mock) -> ice_servers.IceServers:
    """ICE servers API fixture."""
    auth_cloud_mock.servicehandlers_server = "example.com/test"
    auth_cloud_mock.id_token = "mock-id-token"
    return ice_servers.IceServers(auth_cloud_mock)


@pytest.fixture
def mock_ice_servers(aioclient_mock: AiohttpClientMocker):
    """Mock ICE servers."""
    aioclient_mock.get(
        "https://example.com/test/webrtc/ice_servers",
        json=[
            {
                "urls": "turn:example.com:80",
                "username": "12345678:test-user",
                "credential": "secret-value",
            },
        ],
    )


async def test_ice_servers_listener_registration_triggers_periodic_ice_servers_update(
    ice_servers_api: ice_servers.IceServers,
    mock_ice_servers,
):
    """Test that registering an ICE servers listener triggers a periodic update."""
    times_register_called_successfully = 0

    ice_servers_api._get_refresh_sleep_time = lambda: 0

    async def register_ice_servers(ice_servers: list[RTCIceServer]):
        nonlocal times_register_called_successfully

        # These asserts will silently fail and variable will not be incremented
        assert len(ice_servers) == 1
        assert ice_servers[0].urls == "turn:example.com:80"
        assert ice_servers[0].username == "12345678:test-user"
        assert ice_servers[0].credential == "secret-value"

        times_register_called_successfully += 1

        def unregister():
            pass

        return unregister

    unregister = await ice_servers_api.async_register_ice_servers_listener(
        register_ice_servers,
    )

    # Let the periodic update run once
    await asyncio.sleep(0)
    # Let the periodic update run again
    await asyncio.sleep(0)

    assert times_register_called_successfully == 2

    unregister()

    # The periodic update should not run again
    await asyncio.sleep(0)

    assert times_register_called_successfully == 2

    assert ice_servers_api._refresh_task is None
    assert ice_servers_api._ice_servers == []
    assert ice_servers_api._ice_servers_listener is None
    assert ice_servers_api._ice_servers_listener_unregister is None


async def test_ice_server_refresh_sets_ice_server_list_empty_on_expired_subscription(
    ice_servers_api: ice_servers.IceServers,
    aioclient_mock: AiohttpClientMocker,
):
    """Test that the ICE server list is set to empty when the subscription expires."""
    times_register_called_successfully = 0

    ice_servers_api._get_refresh_sleep_time = lambda: 0

    ice_servers_api.cloud.subscription_expired = True

    async def register_ice_servers(ice_servers: list[RTCIceServer]):
        nonlocal times_register_called_successfully

        # This assert will silently fail and variable will not be incremented
        assert len(ice_servers) == 0

        times_register_called_successfully += 1

        def unregister():
            pass

        return unregister

    await ice_servers_api.async_register_ice_servers_listener(register_ice_servers)

    # Let the periodic update run once
    await asyncio.sleep(0)

    assert ice_servers_api._ice_servers == []

    assert len(aioclient_mock.mock_calls) == 0
    assert times_register_called_successfully == 1
    assert ice_servers_api._refresh_task is not None
    assert ice_servers_api._ice_servers_listener is not None
    assert ice_servers_api._ice_servers_listener_unregister is not None


async def test_ice_server_refresh_sets_ice_server_list_empty_on_401_403_client_error(
    ice_servers_api: ice_servers.IceServers,
    aioclient_mock: AiohttpClientMocker,
):
    """Test that ICE server list is empty when server returns 401 or 403 errors."""
    aioclient_mock.get(
        "https://example.com/test/webrtc/ice_servers",
        status=403,
        json={"message": "Boom!"},
    )

    times_register_called_successfully = 0

    ice_servers_api._get_refresh_sleep_time = lambda: 0

    ice_servers_api._ice_servers = [
        RTCIceServer(
            urls="turn:example.com:80",
            username="12345678:test-user",
            credential="secret-value",
        ),
    ]

    async def register_ice_servers(ice_servers: list[RTCIceServer]):
        nonlocal times_register_called_successfully

        # This assert will silently fail and variable will not be incremented
        assert len(ice_servers) == 0

        times_register_called_successfully += 1

        def unregister():
            pass

        return unregister

    await ice_servers_api.async_register_ice_servers_listener(register_ice_servers)

    # Let the periodic update run once
    await asyncio.sleep(0)

    assert ice_servers_api._ice_servers == []

    assert times_register_called_successfully == 1
    assert ice_servers_api._refresh_task is not None
    assert ice_servers_api._ice_servers_listener is not None
    assert ice_servers_api._ice_servers_listener_unregister is not None


async def test_ice_server_refresh_keeps_ice_server_list_on_other_client_errors(
    ice_servers_api: ice_servers.IceServers,
    aioclient_mock,
):
    """Test that ICE server list is not set to empty when server returns an error."""
    aioclient_mock.get(
        "https://example.com/test/webrtc/ice_servers",
        status=500,
        json={"message": "Boom!"},
    )

    times_register_called_successfully = 0

    ice_servers_api._get_refresh_sleep_time = lambda: 0

    ice_servers_api._ice_servers = [
        RTCIceServer(
            urls="turn:example.com:80",
            username="12345678:test-user",
            credential="secret-value",
        ),
    ]

    async def register_ice_servers(ice_servers: list[RTCIceServer]):
        nonlocal times_register_called_successfully

        # These asserts will silently fail and variable will not be incremented
        assert len(ice_servers) == 1
        assert ice_servers[0].urls == "turn:example.com:80"
        assert ice_servers[0].username == "12345678:test-user"
        assert ice_servers[0].credential == "secret-value"

        times_register_called_successfully += 1

        def unregister():
            pass

        return unregister

    await ice_servers_api.async_register_ice_servers_listener(register_ice_servers)

    # Let the periodic update run once
    await asyncio.sleep(0)

    assert ice_servers_api._ice_servers != []

    assert times_register_called_successfully == 1
    assert ice_servers_api._refresh_task is not None
    assert ice_servers_api._ice_servers_listener is not None
    assert ice_servers_api._ice_servers_listener_unregister is not None


def test_get_refresh_sleep_time(ice_servers_api: ice_servers.IceServers):
    """Test get refresh sleep time."""
    min_timestamp = 8888888888

    ice_servers_api._ice_servers = [
        RTCIceServer(urls="turn:example.com:80", username="9999999999:test-user"),
        RTCIceServer(
            urls="turn:example.com:80",
            username=f"{min_timestamp!s}:test-user",
        ),
    ]

    assert (
        ice_servers_api._get_refresh_sleep_time()
        == min_timestamp - int(time.time()) - 3600
    )


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

    ice_servers_api._ice_servers = [
        RTCIceServer(urls="turn:example.com:80", username="12345678:test-user"),
        RTCIceServer(
            urls="turn:example.com:80",
            username=f"{min_timestamp!s}:test-user",
        ),
    ]

    refresh_time = ice_servers_api._get_refresh_sleep_time()

    assert refresh_time >= 100
    assert refresh_time <= 300
