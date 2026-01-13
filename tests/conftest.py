"""Set up some common test helper things."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from aiohttp import web
from freezegun import freeze_time
import jwt
import pytest

import hass_nabucasa

from .common import WELL_KNOWN_SERVICE_DISCOVERY_JSON, FreezeTimeFixture, MockClient
from .utils.aiohttp import AiohttpClientMocker, mock_aiohttp_client

logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
def service_discovery_fixture_data():
    """Load service discovery fixture data from JSON file."""
    with WELL_KNOWN_SERVICE_DISCOVERY_JSON.open() as f:
        return json.load(f)


@pytest.fixture(autouse=True, name="frozen_time")
def freeze_time_fixture() -> Generator[FreezeTimeFixture, Any]:
    """Freeze time for all tests by default."""
    original_timestamp = datetime.timestamp

    def consistent_timestamp(self):
        """Return timestamp rounded to integer seconds for test consistency."""
        return int(original_timestamp(self))

    with (
        freeze_time("2018-09-17 12:00:00", tick=True) as time_freezer,
        patch("datetime.datetime.timestamp", consistent_timestamp),
    ):
        yield time_freezer


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

    async def update_token(
        id_token,
        access_token,
        refresh_token=None,
    ):
        cloud.id_token = id_token
        cloud.access_token = access_token
        if refresh_token is not None:
            cloud.refresh_token = refresh_token

    cloud.update_token = MagicMock(side_effect=update_token)
    cloud.ensure_not_connected = AsyncMock()

    yield cloud

    await cloud.websession.close()


@pytest.fixture
def auth_cloud_mock(cloud_mock):
    """Return an authenticated cloud instance."""
    cloud_mock.accounts = MagicMock(
        instance_resolve_dns_cname=AsyncMock(),
    )
    cloud_mock.auth.async_check_token.side_effect = AsyncMock()
    cloud_mock.subscription_expired = False
    cloud_mock.instance = MagicMock(
        resolve_dns_cname=AsyncMock(),
        register=AsyncMock(),
        snitun_token=AsyncMock(),
        connection=AsyncMock(),
        create_dns_challenge_record=AsyncMock(),
        cleanup_dns_challenge_record=AsyncMock(),
    )
    cloud_mock.events = MagicMock(
        publish=AsyncMock(),
    )
    return cloud_mock


@pytest.fixture
def cloud_client(cloud_mock: MagicMock) -> MockClient:
    """Return cloud client impl."""
    return cast("MockClient", cloud_mock.client)


@pytest.fixture
async def cloud(
    aioclient_mock: AiohttpClientMocker,
    loop: asyncio.AbstractEventLoop,
    tmp_path: Path,
) -> AsyncGenerator[hass_nabucasa.Cloud, Any]:
    """Create a cloud fixture."""
    client_session = aioclient_mock.create_session(loop)
    client = MockClient(tmp_path, loop, client_session)

    cloud_dir = tmp_path / ".cloud"
    cloud_dir.mkdir(exist_ok=True)

    with (
        patch("pathlib.Path.chmod"),
        patch("pathlib.Path.read_text", return_value=""),
        patch("pathlib.Path.write_bytes"),
        patch("pathlib.Path.write_text"),
        patch("shutil.rmtree"),
    ):
        cloud = hass_nabucasa.Cloud(
            client,
            "development",
            cognito_client_id="abc123",
            region="xx-earth-616",
            api_server="api.example.com",
            account_link_server="account-link.example.com",
            acme_server="acme.example.com",
            relayer_server="relayer.example.com",
            remotestate_server="remotestate.example.com",
            servicehandlers_server="servicehandlers.example.com",
        )

        fake_secret = "fake-test-secret"

        id_token_claims = {
            "cognito:username": "test@example.com",
            "custom:sub-exp": "2019-09-17",
            "iat": 1537185600,
            "exp": 1537185600 + (365 * 24 * 60 * 60),
            "token_use": "id",
        }

        access_token_claims = {
            "client_id": "test-client-id",
            "username": "test@example.com",
            "token_use": "access",
            "scope": "aws.cognito.signin.user.admin",
            "iat": 1537185600,
            "exp": 1537185600 + 3600,
        }

        refresh_token_claims = {
            "client_id": "test-client-id",
            "username": "test@example.com",
            "token_use": "refresh",
            "iat": 1537185600,
            "exp": 1537185600 + (30 * 24 * 60 * 60),
        }

        id_token = jwt.encode(id_token_claims, fake_secret, algorithm="HS256")
        access_token = jwt.encode(access_token_claims, fake_secret, algorithm="HS256")
        refresh_token = jwt.encode(refresh_token_claims, fake_secret, algorithm="HS256")
        renewed_id_token = jwt.encode(id_token_claims, fake_secret, algorithm="HS256")
        renewed_access_token = jwt.encode(
            access_token_claims, fake_secret, algorithm="HS256"
        )

        mock_cognito = MagicMock()
        mock_cognito.id_token = renewed_id_token
        mock_cognito.access_token = renewed_access_token
        cloud.auth._create_cognito_client = MagicMock(return_value=mock_cognito)

        cloud.auth.async_check_token = AsyncMock()

        cloud.id_token = id_token
        cloud.access_token = access_token
        cloud.refresh_token = refresh_token

        yield cloud
        await client_session.close()


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
