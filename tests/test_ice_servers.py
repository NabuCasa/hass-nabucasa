"""Test the ICE servers module."""

import asyncio
import time
from unittest.mock import patch

import pytest
from syrupy import SnapshotAssertion
from webrtc_models import RTCIceServer

from hass_nabucasa import Cloud, ice_servers
from tests.common import extract_log_messages
from tests.utils.aiohttp import AiohttpClientMocker


@pytest.fixture
def mock_ice_servers(aioclient_mock: AiohttpClientMocker, cloud: Cloud):
    """Mock ICE servers."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/v2/webrtc/ice_servers",
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


@pytest.fixture
def mock_refresh_time_zero():
    """Mock refresh time to a short interval for testing."""
    with patch(
        "hass_nabucasa.ice_servers.IceServers._get_refresh_sleep_time",
        lambda _: 0,
    ):
        yield


async def test_ice_servers_listener_registration_triggers_periodic_ice_servers_update(
    mock_ice_servers: None,
    mock_refresh_time_zero: None,
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
):
    """Test that registering an ICE servers listener triggers a periodic update."""
    times_register_called_successfully = 0

    async def register_ice_servers(ice_servers_to_register: list[RTCIceServer]):
        nonlocal times_register_called_successfully

        # These asserts will silently fail and variable will not be incremented
        assert len(ice_servers_to_register) == 2
        assert ice_servers_to_register[0].urls == "stun:example.com:80"
        assert ice_servers_to_register[0].username is None
        assert ice_servers_to_register[0].credential is None

        assert ice_servers_to_register[1].urls == "turn:example.com:80"
        assert ice_servers_to_register[1].username == "some-user"
        assert ice_servers_to_register[1].credential == "secret-value"

        assert cloud.ice_servers._nabucasa_ice_servers[0].urls == "stun:example.com:80"
        assert cloud.ice_servers._nabucasa_ice_servers[0].username is None
        assert cloud.ice_servers._nabucasa_ice_servers[0].credential is None
        assert cloud.ice_servers._nabucasa_ice_servers[1].urls == "turn:example.com:80"
        assert cloud.ice_servers._nabucasa_ice_servers[1].username == "some-user"
        assert cloud.ice_servers._nabucasa_ice_servers[1].credential == "secret-value"
        assert (
            cloud.ice_servers._nabucasa_ice_servers[1].expiration_timestamp
            == int(time.time()) + 3600
        )

        times_register_called_successfully += 1

        def unregister():
            pass

        return unregister

    unregister = await cloud.ice_servers.async_register_ice_servers_listener(
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

    assert cloud.ice_servers._refresh_task is None
    assert cloud.ice_servers._nabucasa_ice_servers == []
    assert cloud.ice_servers._ice_servers_listener is None
    assert cloud.ice_servers._ice_servers_listener_unregister is None

    assert extract_log_messages(caplog) == snapshot


async def test_ice_server_refresh_sets_ice_server_list_empty_on_expired_subscription(
    mock_ice_servers: None,
    mock_refresh_time_zero: None,
    cloud_with_expired_subscription: Cloud,
    aioclient_mock: AiohttpClientMocker,
):
    """Test that the ICE server list is set to empty when the subscription expires."""
    cloud = cloud_with_expired_subscription
    times_register_called_successfully = 0

    async def register_ice_servers(ice_servers: list[RTCIceServer]):
        nonlocal times_register_called_successfully

        # This assert will silently fail and variable will not be incremented
        assert len(ice_servers) == 0

        times_register_called_successfully += 1

        def unregister():
            pass

        return unregister

    unregister = await cloud.ice_servers.async_register_ice_servers_listener(
        register_ice_servers
    )

    # Let the periodic update run once
    await asyncio.sleep(0)

    assert cloud.ice_servers._nabucasa_ice_servers == []

    assert len(aioclient_mock.mock_calls) == 0
    assert times_register_called_successfully == 1
    assert cloud.ice_servers._refresh_task is not None
    assert cloud.ice_servers._ice_servers_listener is not None
    assert cloud.ice_servers._ice_servers_listener_unregister is not None

    # Clean up the task
    unregister()


async def test_ice_server_refresh_sets_ice_server_list_empty_on_401_403_client_error(
    mock_refresh_time_zero: None,
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
):
    """Test that ICE server list is empty when server returns 401 or 403 errors."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/v2/webrtc/ice_servers",
        status=403,
        json={"message": "Boom!"},
    )

    times_register_called_successfully = 0

    cloud.ice_servers._nabucasa_ice_servers = [
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

    async def register_ice_servers(ice_servers: list[RTCIceServer]):
        nonlocal times_register_called_successfully

        # This assert will silently fail and variable will not be incremented
        assert len(ice_servers) == 0

        times_register_called_successfully += 1

        def unregister():
            pass

        return unregister

    unregister = await cloud.ice_servers.async_register_ice_servers_listener(
        register_ice_servers
    )

    # Let the periodic update run once
    await asyncio.sleep(0)

    assert cloud.ice_servers._nabucasa_ice_servers == []

    assert times_register_called_successfully == 1
    assert cloud.ice_servers._refresh_task is not None
    assert cloud.ice_servers._ice_servers_listener is not None
    assert cloud.ice_servers._ice_servers_listener_unregister is not None

    # Clean up the task
    unregister()


async def test_ice_server_refresh_keeps_ice_server_list_on_other_client_errors(
    cloud: Cloud,
    aioclient_mock: AiohttpClientMocker,
):
    """Test that ICE server list is not set to empty when server returns an error."""
    aioclient_mock.get(
        f"https://{cloud.servicehandlers_server}/v2/webrtc/ice_servers",
        status=500,
        json={"message": "Boom!"},
    )

    times_register_called_successfully = 0

    cloud.ice_servers._get_refresh_sleep_time = lambda: 0

    cloud.ice_servers._nabucasa_ice_servers = [
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

    async def register_ice_servers(ice_servers: list[RTCIceServer]):
        nonlocal times_register_called_successfully

        # These asserts will silently fail and variable will not be incremented
        assert len(ice_servers) == 2
        assert ice_servers[0].urls == "stun:example.com:80"
        assert ice_servers[0].username is None
        assert ice_servers[0].credential is None
        assert ice_servers[1].urls == "turn:example.com:80"
        assert ice_servers[1].username == "some-user"
        assert ice_servers[1].credential == "secret-value"

        times_register_called_successfully += 1

        def unregister():
            pass

        return unregister

    unregister = await cloud.ice_servers.async_register_ice_servers_listener(
        register_ice_servers
    )

    # Let the periodic update run once
    await asyncio.sleep(0)

    assert cloud.ice_servers._nabucasa_ice_servers != []

    assert times_register_called_successfully == 1
    assert cloud.ice_servers._refresh_task is not None
    assert cloud.ice_servers._ice_servers_listener is not None
    assert cloud.ice_servers._ice_servers_listener_unregister is not None

    # Clean up the task
    unregister()


def test_get_refresh_sleep_time(cloud: Cloud):
    """Test get refresh sleep time."""
    min_timestamp = 86400

    cloud.ice_servers._nabucasa_ice_servers = [
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

    assert cloud.ice_servers._get_refresh_sleep_time() == min_timestamp - 3600


def test_get_refresh_sleep_time_no_turn_servers(
    cloud: Cloud,
):
    """Test get refresh sleep time."""
    refresh_time = cloud.ice_servers._get_refresh_sleep_time()

    assert refresh_time >= 3600
    assert refresh_time <= 43200


def test_get_refresh_sleep_time_expiration_less_than_one_hour(
    cloud: Cloud,
):
    """Test get refresh sleep time."""
    min_timestamp = 10

    cloud.ice_servers._nabucasa_ice_servers = [
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

    refresh_time = cloud.ice_servers._get_refresh_sleep_time()

    assert refresh_time >= 100
    assert refresh_time <= 300
