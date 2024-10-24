"""Test the ICE servers module."""

import asyncio
import time

import pytest
from webrtc_models import RTCIceServer

from hass_nabucasa import ice_servers


@pytest.fixture
def ice_servers_api(auth_cloud_mock) -> ice_servers.IceServers:
    """ICE servers API fixture."""
    auth_cloud_mock.servicehandlers_server = "example.com/test"
    auth_cloud_mock.id_token = "mock-id-token"
    return ice_servers.IceServers(auth_cloud_mock)


@pytest.fixture(autouse=True)
def mock_ice_servers(aioclient_mock):
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
):
    """Test that registering an ICE servers listener triggers a periodic update."""
    times_register_called_successfully = 0

    ice_servers_api._get_refresh_sleep_time = lambda: -1

    async def register_ice_server(ice_server: RTCIceServer):
        nonlocal times_register_called_successfully

        # There asserts will silently fail and variable will not be incremented
        assert ice_server.urls == "turn:example.com:80"
        assert ice_server.username == "12345678:test-user"
        assert ice_server.credential == "secret-value"

        times_register_called_successfully += 1

        def unregister():
            pass

        return unregister

    unregister = await ice_servers_api.async_register_ice_servers_listener(
        register_ice_server,
    )

    # Let the periodic update run once
    await asyncio.sleep(0)
    # Let the periodic update run again
    await asyncio.sleep(0)

    unregister()

    assert times_register_called_successfully == 2

    assert ice_servers_api._refresh_task is None
    assert ice_servers_api._ice_servers == []
    assert ice_servers_api._ice_servers_listener is None
    assert ice_servers_api._ice_servers_listener_unregister == []


async def test_ice_servers_listener_deregistration_stops_periodic_ice_servers_update(
    ice_servers_api: ice_servers.IceServers,
):
    """Test that deregistering an ICE servers listener stops the periodic update."""
    times_register_called_successfully = 0

    ice_servers_api._get_refresh_sleep_time = lambda: -1

    async def register_ice_server(ice_server: RTCIceServer):
        nonlocal times_register_called_successfully

        # There asserts will silently fail and variable will not be incremented
        assert ice_server.urls == "turn:example.com:80"
        assert ice_server.username == "12345678:test-user"
        assert ice_server.credential == "secret-value"

        times_register_called_successfully += 1

        def unregister():
            pass

        return unregister

    unregister = await ice_servers_api.async_register_ice_servers_listener(
        register_ice_server,
    )

    # Let the periodic update run once
    await asyncio.sleep(0)

    unregister()

    # The periodic update should not run again
    await asyncio.sleep(0)

    assert times_register_called_successfully == 1

    assert ice_servers_api._refresh_task is None
    assert ice_servers_api._ice_servers == []
    assert ice_servers_api._ice_servers_listener is None
    assert ice_servers_api._ice_servers_listener_unregister == []


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
    assert ice_servers_api._get_refresh_sleep_time() == 3600


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
