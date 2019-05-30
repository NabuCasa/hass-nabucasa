"""Test the cloud.iot module."""
import asyncio
from unittest.mock import patch, MagicMock, PropertyMock, Mock

from aiohttp import WSMsgType, client_exceptions, web
import pytest

from hass_nabucasa import Cloud, iot, auth as auth_api, MODE_DEV

from .common import mock_coro, mock_coro_func


@pytest.fixture
def mock_client(cloud_mock):
    """Mock the IoT client."""
    client = MagicMock()
    websession = MagicMock()
    type(client).closed = PropertyMock(side_effect=[False, True])

    # Trigger cancelled error to avoid reconnect.
    org_websession = cloud_mock.websession
    with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
        websession.ws_connect.side_effect = lambda *a, **kw: mock_coro(client)
        cloud_mock.websession = websession
        yield client

    cloud_mock.websession = org_websession


@pytest.fixture
def mock_handle_message():
    """Mock handle message."""
    with patch("hass_nabucasa.iot.async_handle_message") as mock:
        yield mock


@pytest.fixture
def cloud_mock_iot(cloud_mock):
    """Mock cloud class."""
    cloud_mock.subscription_expired = False
    cloud_mock.run_executor = Mock(return_value=mock_coro())
    yield cloud_mock


async def test_cloud_calling_handler(mock_client, mock_handle_message, cloud_mock_iot):
    """Test we call handle message with correct info."""
    conn = iot.CloudIoT(cloud_mock_iot)
    mock_client.receive.return_value = mock_coro(
        MagicMock(
            type=WSMsgType.text,
            json=MagicMock(
                return_value={
                    "msgid": "test-msg-id",
                    "handler": "test-handler",
                    "payload": "test-payload",
                }
            ),
        )
    )
    mock_handle_message.return_value = mock_coro("response")
    mock_client.send_json.return_value = mock_coro(None)

    await conn.connect()

    # Check that we sent message to handler correctly
    assert len(mock_handle_message.mock_calls) == 1
    cloud, handler_name, payload = mock_handle_message.mock_calls[0][1]

    assert cloud is cloud_mock_iot
    assert handler_name == "test-handler"
    assert payload == "test-payload"

    # Check that we forwarded response from handler to cloud
    assert len(mock_client.send_json.mock_calls) == 1
    assert mock_client.send_json.mock_calls[0][1][0] == {
        "msgid": "test-msg-id",
        "payload": "response",
    }


async def test_connection_msg_for_unknown_handler(mock_client, cloud_mock_iot):
    """Test a msg for an unknown handler."""
    conn = iot.CloudIoT(cloud_mock_iot)
    mock_client.receive.return_value = mock_coro(
        MagicMock(
            type=WSMsgType.text,
            json=MagicMock(
                return_value={
                    "msgid": "test-msg-id",
                    "handler": "non-existing-handler",
                    "payload": "test-payload",
                }
            ),
        )
    )
    mock_client.send_json.return_value = mock_coro(None)

    await conn.connect()

    # Check that we sent the correct error
    assert len(mock_client.send_json.mock_calls) == 1
    assert mock_client.send_json.mock_calls[0][1][0] == {
        "msgid": "test-msg-id",
        "error": "unknown-handler",
    }


async def test_connection_msg_for_handler_raising(
    mock_client, mock_handle_message, cloud_mock_iot
):
    """Test we sent error when handler raises exception."""
    conn = iot.CloudIoT(cloud_mock_iot)
    mock_client.receive.return_value = mock_coro(
        MagicMock(
            type=WSMsgType.text,
            json=MagicMock(
                return_value={
                    "msgid": "test-msg-id",
                    "handler": "test-handler",
                    "payload": "test-payload",
                }
            ),
        )
    )
    mock_handle_message.side_effect = Exception("Broken")
    mock_client.send_json.return_value = mock_coro(None)

    await conn.connect()

    # Check that we sent the correct error
    assert len(mock_client.send_json.mock_calls) == 1
    assert mock_client.send_json.mock_calls[0][1][0] == {
        "msgid": "test-msg-id",
        "error": "exception",
    }


async def test_handler_forwarding():
    """Test we forward messages to correct handler."""
    handler = MagicMock()
    handler.return_value = mock_coro()
    cloud = object()
    with patch.dict(iot.HANDLERS, {"test": handler}):
        await iot.async_handle_message(cloud, "test", "payload")

    assert len(handler.mock_calls) == 1
    r_cloud, payload = handler.mock_calls[0][1]
    assert r_cloud is cloud
    assert payload == "payload"


async def test_handling_core_messages_logout(cloud_mock_iot):
    """Test handling core messages."""
    cloud_mock_iot.logout.return_value = mock_coro()
    await iot.async_handle_cloud(
        cloud_mock_iot, {"action": "logout", "reason": "Logged in at two places."}
    )
    assert len(cloud_mock_iot.logout.mock_calls) == 1


async def test_cloud_getting_disconnected_by_server(
    mock_client, caplog, cloud_mock_iot
):
    """Test server disconnecting instance."""
    conn = iot.CloudIoT(cloud_mock_iot)
    mock_client.receive.return_value = mock_coro(MagicMock(type=WSMsgType.CLOSING))

    with patch("asyncio.sleep", side_effect=[mock_coro(), asyncio.CancelledError]):
        await conn.connect()

    assert "Connection closed" in caplog.text


async def test_cloud_receiving_bytes(mock_client, caplog, cloud_mock_iot):
    """Test server disconnecting instance."""
    conn = iot.CloudIoT(cloud_mock_iot)
    mock_client.receive.return_value = mock_coro(MagicMock(type=WSMsgType.BINARY))

    await conn.connect()

    assert "Connection closed: Received non-Text message" in caplog.text


async def test_cloud_sending_invalid_json(mock_client, caplog, cloud_mock_iot):
    """Test cloud sending invalid JSON."""
    conn = iot.CloudIoT(cloud_mock_iot)
    mock_client.receive.return_value = mock_coro(
        MagicMock(type=WSMsgType.TEXT, json=MagicMock(side_effect=ValueError))
    )

    await conn.connect()

    assert "Connection closed: Received invalid JSON." in caplog.text


async def test_cloud_check_token_raising(mock_client, caplog, cloud_mock_iot):
    """Test cloud unable to check token."""
    conn = iot.CloudIoT(cloud_mock_iot)
    cloud_mock_iot.run_executor = mock_coro_func(exception=auth_api.CloudError("BLA"))

    await conn.connect()

    assert "Unable to refresh token: BLA" in caplog.text


async def test_cloud_connect_invalid_auth(mock_client, caplog, cloud_mock_iot):
    """Test invalid auth detected by server."""
    conn = iot.CloudIoT(cloud_mock_iot)
    mock_client.receive.side_effect = client_exceptions.WSServerHandshakeError(
        None, None, status=401
    )

    await conn.connect()

    assert "Connection closed: Invalid auth." in caplog.text


async def test_cloud_unable_to_connect(mock_client, caplog, cloud_mock_iot):
    """Test unable to connect error."""
    conn = iot.CloudIoT(cloud_mock_iot)
    mock_client.receive.side_effect = client_exceptions.ClientError(None, None)

    await conn.connect()

    assert "Unable to connect:" in caplog.text


async def test_cloud_random_exception(mock_client, caplog, cloud_mock_iot):
    """Test random exception."""
    conn = iot.CloudIoT(cloud_mock_iot)
    mock_client.receive.side_effect = Exception

    await conn.connect()

    assert "Unexpected error" in caplog.text


async def test_refresh_token_before_expiration_fails(cloud_mock):
    """Test that we don't connect if token is expired."""
    cloud_mock.subscription_expired = True
    conn = iot.CloudIoT(cloud_mock)

    await conn.connect()

    assert len(cloud_mock.auth.check_token.mock_calls) == 1
    assert len(cloud_mock.client.mock_user) == 1


async def test_handler_alexa(cloud_mock):
    """Test handler Alexa."""
    cloud_mock.client.mock_return.append({"test": 5})
    resp = await iot.async_handle_alexa(cloud_mock, {"test-discovery": True})

    assert len(cloud_mock.client.mock_alexa) == 1
    assert resp == {"test": 5}


async def test_handler_google(cloud_mock):
    """Test handler Google."""
    cloud_mock.client.mock_return.append({"test": 5})
    resp = await iot.async_handle_google_actions(cloud_mock, {"test-discovery": True})

    assert len(cloud_mock.client.mock_google) == 1
    assert resp == {"test": 5}


async def test_handler_webhook(cloud_mock):
    """Test handler Webhook."""
    cloud_mock.client.mock_return.append({"test": 5})
    resp = await iot.async_handle_webhook(cloud_mock, {"test-discovery": True})

    assert len(cloud_mock.client.mock_webhooks) == 1
    assert resp == {"test": 5}


async def test_handler_remote_sni(cloud_mock):
    """Test handler Webhook."""
    cloud_mock.remote.handle_connection_requests = Mock(return_value=mock_coro())
    cloud_mock.remote.snitun_server = "1.1.1.1"
    resp = await iot.async_handle_remote_sni(cloud_mock, {"ip_address": "8.8.8.8"})

    assert cloud_mock.remote.handle_connection_requests.called
    assert cloud_mock.remote.handle_connection_requests.mock_calls[0][1][0] == "8.8.8.8"
    assert resp == {"server": "1.1.1.1"}


async def test_refresh_token_expired(cloud_mock):
    """Test handling Unauthenticated error raised if refresh token expired."""
    cloud_mock.subscription_expired = True
    conn = iot.CloudIoT(cloud_mock)

    await conn.connect()

    assert len(cloud_mock.auth.check_token.mock_calls) == 1
    assert len(cloud_mock.client.mock_user) == 1


async def test_send_message_not_connected(cloud_mock_iot):
    """Test sending a message that expects no answer."""
    cloud_iot = iot.CloudIoT(cloud_mock_iot)

    with pytest.raises(iot.NotConnected):
        await cloud_iot.async_send_message("webhook", {"msg": "yo"})


async def test_send_message_no_answer(cloud_mock_iot):
    """Test sending a message that expects no answer."""
    cloud_iot = iot.CloudIoT(cloud_mock_iot)
    cloud_iot.state = iot.STATE_CONNECTED
    cloud_iot.client = MagicMock(send_json=MagicMock(return_value=mock_coro()))

    await cloud_iot.async_send_message("webhook", {"msg": "yo"}, expect_answer=False)
    assert not cloud_iot._response_handler
    assert len(cloud_iot.client.send_json.mock_calls) == 1
    msg = cloud_iot.client.send_json.mock_calls[0][1][0]
    assert msg["handler"] == "webhook"
    assert msg["payload"] == {"msg": "yo"}


async def test_send_message_answer(loop, cloud_mock_iot):
    """Test sending a message that expects no answer."""
    cloud_iot = iot.CloudIoT(cloud_mock_iot)
    cloud_iot.state = iot.STATE_CONNECTED
    cloud_iot.client = MagicMock(send_json=MagicMock(return_value=mock_coro()))

    uuid = 5

    with patch("hass_nabucasa.iot.uuid.uuid4", return_value=MagicMock(hex=uuid)):
        send_task = loop.create_task(
            cloud_iot.async_send_message("webhook", {"msg": "yo"})
        )
        await asyncio.sleep(0)

    assert len(cloud_iot.client.send_json.mock_calls) == 1
    assert len(cloud_iot._response_handler) == 1
    msg = cloud_iot.client.send_json.mock_calls[0][1][0]
    assert msg["handler"] == "webhook"
    assert msg["payload"] == {"msg": "yo"}

    cloud_iot._response_handler[uuid].set_result({"response": True})
    response = await send_task
    assert response == {"response": True}
