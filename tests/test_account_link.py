"""Test Account Linking tools."""

import asyncio
from unittest.mock import AsyncMock, Mock

from aiohttp import web
import pytest

from hass_nabucasa import account_link


async def create_account_link_server(aiohttp_client, handle_server_msgs):
    """Create a websocket server."""

    async def websocket_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        try:
            await handle_server_msgs(ws)
        finally:
            await ws.close()

        return ws

    app = web.Application()
    app.add_routes([web.get("/ws", websocket_handler)])
    client = await aiohttp_client(app)
    return await client.ws_connect("/ws")


async def create_helper_instance(
    aiohttp_client,
    handle_server_msgs,
    service,
) -> account_link.AuthorizeAccountHelper:
    """Create a auth helper instance."""
    client = await create_account_link_server(aiohttp_client, handle_server_msgs)
    mock_cloud = Mock(
        client=Mock(websession=Mock(ws_connect=AsyncMock(return_value=client))),
    )
    return account_link.AuthorizeAccountHelper(mock_cloud, service)


async def test_auth_helper_works(aiohttp_client):
    """Test authorize account helper."""
    received = []

    async def handle_msgs(ws):
        """Handle the messages on the server."""
        data = await ws.receive_json()
        received.append(data)
        await ws.send_json({"authorize_url": "http://mock-url"})
        await ws.send_json({"tokens": {"refresh_token": "abcd", "expires_in": 10}})

    helper = await create_helper_instance(aiohttp_client, handle_msgs, "mock-service")

    assert await helper.async_get_authorize_url() == "http://mock-url"

    assert await helper.async_get_tokens() == {
        "refresh_token": "abcd",
        "expires_in": 10,
        "service": "mock-service",
    }

    assert helper._client is None
    assert len(received) == 1
    assert received[0] == {"service": "mock-service"}


async def test_auth_helper_unknown_service(aiohttp_client):
    """Test authorize account helper."""

    async def handle_msgs(ws):
        """Handle the messages on the server."""
        await ws.receive_json()
        await ws.send_json({"error": "unknown"})

    helper = await create_helper_instance(aiohttp_client, handle_msgs, "mock-service")

    with pytest.raises(account_link.AccountLinkException) as err:
        await helper.async_get_authorize_url()
    assert err.value.code == "unknown"


async def test_auth_helper_token_timeout(aiohttp_client):
    """Test timeout while waiting for tokens."""

    async def handle_msgs(ws):
        """Handle the messages on the server."""
        await ws.receive_json()
        await ws.send_json({"authorize_url": "http://mock-url"})
        await ws.send_json({"error": "timeout"})

    helper = await create_helper_instance(aiohttp_client, handle_msgs, "mock-service")

    await helper.async_get_authorize_url()

    with pytest.raises(asyncio.TimeoutError):
        await helper.async_get_tokens()


async def test_auth_helper_token_other_error(aiohttp_client):
    """Test error while waiting for tokens."""

    async def handle_msgs(ws):
        """Handle the messages on the server."""
        await ws.receive_json()
        await ws.send_json({"authorize_url": "http://mock-url"})
        await ws.send_json({"error": "something"})

    helper = await create_helper_instance(aiohttp_client, handle_msgs, "mock-service")

    await helper.async_get_authorize_url()

    with pytest.raises(account_link.AccountLinkException) as err:
        await helper.async_get_tokens()

    assert err.value.code == "something"
