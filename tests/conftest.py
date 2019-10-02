"""Set up some common test helper things."""
import asyncio
import logging
from unittest.mock import patch, MagicMock, PropertyMock

from aiohttp import web
import pytest

from .utils.aiohttp import mock_aiohttp_client
from .common import TestClient, mock_coro

logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
async def aioclient_mock(loop):
    """Fixture to mock aioclient calls."""
    with mock_aiohttp_client(loop) as mock_session:
        yield mock_session


@pytest.fixture
async def cloud_mock(loop, aioclient_mock):
    """Simple cloud mock."""
    cloud = MagicMock()
    cloud.run_task = loop.create_task

    def _executor(call, *args):
        """Run executor."""
        return loop.run_in_executor(None, call, *args)

    cloud.run_executor = _executor

    cloud.websession = aioclient_mock.create_session(loop)
    cloud.client = TestClient(loop, cloud.websession)

    yield cloud

    await cloud.websession.close()


@pytest.fixture
def auth_cloud_mock(cloud_mock):
    """Return an authenticated cloud instance."""
    cloud_mock.auth.async_check_token.side_effect = mock_coro
    return cloud_mock


@pytest.fixture
def cloud_client(cloud_mock):
    """Return cloud client impl."""
    yield cloud_mock.client


@pytest.fixture
def mock_cognito():
    """Mock warrant."""
    with patch("hass_nabucasa.auth.CognitoAuth._cognito") as mock_cog:
        yield mock_cog()


@pytest.fixture
def mock_iot_client(cloud_mock):
    """Mock a base IoT client."""
    client = MagicMock()
    websession = MagicMock()
    type(client).closed = PropertyMock(side_effect=[False, True])

    # Trigger cancelled error to avoid reconnect.
    org_websession = cloud_mock.websession
    with patch(
        "hass_nabucasa.iot_base.BaseIoT._wait_retry", side_effect=asyncio.CancelledError
    ):
        websession.ws_connect.side_effect = lambda *a, **kw: mock_coro(client)
        cloud_mock.websession = websession
        yield client

    cloud_mock.websession = org_websession


class DisconnectMockServer(Exception):
    """Disconnect the mock server."""


@pytest.fixture
async def ws_server(aiohttp_client):
    """Create a mock WS server to connect to and returns a connected client."""

    async def create_client_to_server(handle_server_msg):
        """Create a websocket server."""

        async def websocket_handler(request):

            ws = web.WebSocketResponse()
            await ws.prepare(request)

            async for msg in ws:
                try:
                    await handle_server_msg(msg)
                except DisconnectMockServer:
                    await ws.close()

            return ws

        app = web.Application()
        app.add_routes([web.get("/ws", websocket_handler)])
        client = await aiohttp_client(app)
        return await client.ws_connect("/ws")

    return create_client_to_server
