"""Set up some common test helper things."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from aiohttp import web
import pytest

from .common import MockClient
from .utils.aiohttp import mock_aiohttp_client

logging.basicConfig(level=logging.DEBUG)


@pytest.fixture(name="loop")
async def loop_fixture():
    """Return the event loop."""
    return asyncio.get_running_loop()


@pytest.fixture
async def aioclient_mock(loop):
    """Fixture to mock aioclient calls."""
    with mock_aiohttp_client(loop) as mock_session:
        yield mock_session


@pytest.fixture
async def cloud_mock(loop, aioclient_mock, tmp_path):
    """Yield a simple cloud mock."""
    cloud = MagicMock(name="Mock Cloud", is_logged_in=True)

    def _executor(call, *args):
        """Run executor."""
        return loop.run_in_executor(None, call, *args)

    cloud.run_executor = _executor

    cloud.websession = aioclient_mock.create_session(loop)
    cloud.client = MockClient(tmp_path, loop, cloud.websession)

    async def update_token(id_token, access_token, refresh_token=None):
        cloud.id_token = id_token
        cloud.access_token = access_token
        if refresh_token is not None:
            cloud.refresh_token = refresh_token

    cloud.update_token = MagicMock(side_effect=update_token)

    yield cloud

    await cloud.websession.close()


@pytest.fixture
def auth_cloud_mock(cloud_mock):
    """Return an authenticated cloud instance."""
    cloud_mock.auth.async_check_token.side_effect = AsyncMock()
    cloud_mock.subscription_expired = False
    return cloud_mock


@pytest.fixture
def cloud_client(cloud_mock):
    """Return cloud client impl."""
    return cloud_mock.client


@pytest.fixture
def mock_cognito():
    """Mock warrant."""
    with patch("hass_nabucasa.auth.CognitoAuth._create_cognito_client") as mock_cog:
        yield mock_cog()


@pytest.fixture
def mock_iot_client(cloud_mock):
    """Mock a base IoT client."""

    class Client(MagicMock):
        """Websocket client mock."""

        closed = PropertyMock(return_value=False)

        def auto_close(self, msg_count=1):
            """If the client should disconnect itself after 1 message."""
            Client.closed = PropertyMock(side_effect=msg_count * [False] + [True])

        async def close(self):
            """Close the client."""

    client = Client()
    websession = MagicMock()

    # Trigger cancelled error to avoid reconnect.
    org_websession = cloud_mock.websession
    with patch(
        "hass_nabucasa.iot_base.BaseIoT._wait_retry",
        side_effect=asyncio.CancelledError,
    ):
        websession.ws_connect.side_effect = AsyncMock(return_value=client)
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
        logger = logging.getLogger(f"{__name__}.ws_server")

        async def websocket_handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            # Send a message to trigger IoTBase with
            # `mark_connected_after_first_message`
            await ws.send_json({"msgid": 0, "handler": "hello"})

            async for msg in ws:
                logger.debug("Received msg: %s", msg)
                try:
                    resp = await handle_server_msg(msg)
                    if resp is not None:
                        logger.debug("Sending msg: %s", msg)
                        await ws.send_json(resp)
                except DisconnectMockServer:
                    logger.debug("Closing connection (via DisconnectMockServer)")
                    await ws.close()

            return ws

        app = web.Application()
        app.add_routes([web.get("/ws", websocket_handler)])
        client = await aiohttp_client(app)
        return await client.ws_connect("/ws")

    return create_client_to_server
