"""Test the cloud.iot module."""
import asyncio
from unittest.mock import patch, MagicMock, PropertyMock, Mock

from aiohttp import WSMsgType
import pytest

from hass_nabucasa import iot, iot_base

from .common import mock_coro


@pytest.fixture
def mock_client(cloud_mock):
    """Mock the IoT client."""
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


@pytest.fixture
def cloud_mock_iot(cloud_mock):
    """Mock cloud class."""
    cloud_mock.subscription_expired = False
    cloud_mock.run_executor = Mock(return_value=mock_coro())
    yield cloud_mock


async def test_cloud_calling_handler(mock_client, cloud_mock_iot):
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
    mock_handler = Mock(return_value=mock_coro("response"))
    mock_client.send_json.return_value = mock_coro(None)

    with patch.dict(iot.HANDLERS, {"test-handler": mock_handler}, clear=True):
        await conn.connect()
        await asyncio.sleep(0)

    # Check that we sent message to handler correctly
    assert len(mock_handler.mock_calls) == 1
    cloud, payload = mock_handler.mock_calls[0][1]

    assert cloud is cloud_mock_iot
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
    await asyncio.sleep(0)

    # Check that we sent the correct error
    assert len(mock_client.send_json.mock_calls) == 1
    assert mock_client.send_json.mock_calls[0][1][0] == {
        "msgid": "test-msg-id",
        "error": "unknown-handler",
    }


async def test_connection_msg_for_handler_raising(mock_client, cloud_mock_iot):
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
    mock_client.send_json.return_value = mock_coro(None)

    with patch.dict(
        iot.HANDLERS, {"test-handler": Mock(side_effect=Exception("Broken"))}
    ):
        await conn.connect()
        await asyncio.sleep(0)

    # Check that we sent the correct error
    assert len(mock_client.send_json.mock_calls) == 1
    assert mock_client.send_json.mock_calls[0][1][0] == {
        "msgid": "test-msg-id",
        "error": "exception",
    }


async def test_handling_core_messages_logout(cloud_mock_iot):
    """Test handling core messages."""
    cloud_mock_iot.logout.return_value = mock_coro()
    await iot.async_handle_cloud(
        cloud_mock_iot, {"action": "logout", "reason": "Logged in at two places."}
    )
    assert len(cloud_mock_iot.logout.mock_calls) == 1


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


async def test_send_message_no_answer(cloud_mock_iot):
    """Test sending a message that expects no answer."""
    cloud_iot = iot.CloudIoT(cloud_mock_iot)
    cloud_iot.state = iot_base.STATE_CONNECTED
    cloud_iot.client = MagicMock(send_json=MagicMock(return_value=mock_coro()))

    await cloud_iot.async_send_message("webhook", {"msg": "yo"}, expect_answer=False)
    assert not cloud_iot._response_handler
    assert len(cloud_iot.client.send_json.mock_calls) == 1
    msg = cloud_iot.client.send_json.mock_calls[0][1][0]
    assert msg["handler"] == "webhook"
    assert msg["payload"] == {"msg": "yo"}


async def test_send_message_answer(loop, cloud_mock_iot):
    """Test sending a message that expects an answer."""
    cloud_iot = iot.CloudIoT(cloud_mock_iot)
    cloud_iot.state = iot_base.STATE_CONNECTED
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
