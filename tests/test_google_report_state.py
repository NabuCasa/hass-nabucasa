"""Tests for Google Report State."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientConnectionResetError
import pytest

from hass_nabucasa import iot_base
from hass_nabucasa.google_report_state import ErrorResponse, GoogleReportState

from .common import MockClient
from .conftest import DisconnectMockServer

WAIT_TIMEOUT = 1


async def wait_bounded(awaitable: Any) -> Any:
    """Await with a short bound so a stuck future fails instead of hanging."""
    async with asyncio.timeout(WAIT_TIMEOUT):
        return await awaitable


def create_connected_grs(send_json: AsyncMock | None) -> GoogleReportState:
    """Create a grs instance that is marked connected with a mock client."""
    grs = GoogleReportState(Mock())
    grs.state = iot_base.STATE_CONNECTED
    grs.client = None if send_json is None else Mock(send_json=send_json)
    return grs


async def create_grs(ws_server, server_msg_handler) -> GoogleReportState:
    """Create a grs instance."""
    client = await ws_server(server_msg_handler)
    mock_cloud = Mock(
        subscription_expired=False,
        auth=Mock(async_check_token=AsyncMock()),
        websession=Mock(ws_connect=AsyncMock(return_value=client)),
        client=Mock(spec_set=MockClient),
        service_discovery=Mock(
            action_url=Mock(return_value="wss://mock-report-state-url.com/v1"),
        ),
    )
    return GoogleReportState(mock_cloud)


async def test_ws_server_url():
    """Test generating ws server url."""
    mock_cloud = Mock(
        service_discovery=Mock(
            action_url=Mock(return_value="wss://example.com/v1"),
        ),
    )
    grs = GoogleReportState(mock_cloud)
    assert grs.ws_server_url == "wss://example.com/v1"
    mock_cloud.service_discovery.action_url.assert_called_once_with(
        "google_report_state_websocket"
    )


async def test_send_messages(ws_server):
    """Test that we connect if we are not connected."""
    server_msgs = []

    async def handle_server_msg(msg):
        """Handle a server msg."""
        incoming = msg.json()
        server_msgs.append(incoming["payload"])

        # First msg is ok
        if incoming["payload"]["hello"] == 0:
            return {"msgid": incoming["msgid"], "payload": "mock-response"}

        # Second msg is error
        return {
            "msgid": incoming["msgid"],
            "error": "mock-code",
            "message": "mock-message",
        }

    grs = await create_grs(ws_server, handle_server_msg)
    assert grs.state == iot_base.STATE_DISCONNECTED

    # Test we can handle two simultaneous messages while disconnected
    responses = await asyncio.gather(
        *[grs.async_send_message({"hello": 0}), grs.async_send_message({"hello": 1})],
        return_exceptions=True,
    )
    assert grs.state == iot_base.STATE_CONNECTED
    assert len(responses) == 2
    assert responses[0] == "mock-response"
    assert isinstance(responses[1], ErrorResponse)
    assert responses[1].code == "mock-code"
    assert responses[1].message == "mock-message"

    assert sorted(server_msgs, key=lambda val: val["hello"]) == [
        {"hello": 0},
        {"hello": 1},
    ]

    await grs.disconnect()
    assert grs.state == iot_base.STATE_DISCONNECTED
    assert grs._message_sender_task is None


async def test_max_queue_message(ws_server):
    """Test that we connect if we are not connected."""
    server_msgs = []

    async def handle_server_msg(msg):
        """Handle a server msg."""
        incoming = msg.json()
        server_msgs.append(incoming["payload"])
        return {"msgid": incoming["msgid"], "payload": incoming["payload"]["hello"]}

    grs = await create_grs(ws_server, handle_server_msg)

    # Test we can handle sending more messages than queue fits
    with patch.object(grs, "_async_message_sender"):
        gather_task = asyncio.gather(
            *[grs.async_send_message({"hello": i}) for i in range(150)],
            return_exceptions=True,
        )
        # One per message
        for _ in range(150):
            await asyncio.sleep(0)

    # Start handling messages.
    await grs._async_on_connect()

    # One per message
    for _ in range(150):
        await asyncio.sleep(0)

    assert len(server_msgs) == 100

    results = await gather_task
    assert len(results) == 150
    assert sum(isinstance(result, ErrorResponse) for result in results) == 50

    await grs.disconnect()
    assert grs.state == iot_base.STATE_DISCONNECTED
    assert grs._message_sender_task is None


async def test_disconnect_fails_in_flight_message(ws_server):
    """Test a message sent but not answered fails when the connection drops."""

    async def handle_server_msg(msg):
        """Close the connection without answering."""
        raise DisconnectMockServer

    grs = await create_grs(ws_server, handle_server_msg)

    with pytest.raises(ErrorResponse) as exc_info:
        await wait_bounded(grs.async_send_message({"hello": 0}))

    assert exc_info.value.code == "disconnected"
    assert grs._response_handler == {}

    await grs.disconnect()


async def test_cancel_during_send_fails_message():
    """Test a message fails when the sender is cancelled mid-send."""
    send_started = asyncio.Event()

    async def send_json(_msg):
        send_started.set()
        await asyncio.Event().wait()

    grs = create_connected_grs(AsyncMock(side_effect=send_json))
    await grs._async_on_connect()

    send_task = asyncio.create_task(grs.async_send_message({"hello": 0}))
    await wait_bounded(send_started.wait())
    await grs._async_on_disconnect()

    with pytest.raises(ErrorResponse) as exc_info:
        await wait_bounded(send_task)

    assert exc_info.value.code == "disconnected"


@pytest.mark.parametrize(
    "send_json",
    [
        pytest.param(None, id="not_connected"),
        pytest.param(
            AsyncMock(
                side_effect=ClientConnectionResetError(
                    "Cannot write to closing transport"
                )
            ),
            id="closing_transport",
        ),
    ],
)
async def test_send_error_fails_message_and_keeps_queue(send_json):
    """Test a send error fails that message only and the sender exits cleanly."""
    grs = create_connected_grs(send_json)

    with patch.object(grs, "_async_message_sender"):
        first = asyncio.create_task(grs.async_send_message({"hello": 0}))
        second = asyncio.create_task(grs.async_send_message({"hello": 1}))
        await asyncio.sleep(0)

    await grs._async_on_connect()

    with pytest.raises(ErrorResponse) as exc_info:
        await wait_bounded(first)

    assert exc_info.value.code == "disconnected"

    sender_task = grs._message_sender_task
    assert sender_task is not None
    await wait_bounded(asyncio.wait({sender_task}))
    assert sender_task.exception() is None
    assert grs._to_send.qsize() == 1
    assert not second.done()

    sent = asyncio.Event()
    reconnected_send_json = AsyncMock(side_effect=lambda _msg: sent.set())
    grs.client = Mock(send_json=reconnected_send_json)
    await grs._async_on_connect()
    await wait_bounded(sent.wait())

    reconnected_send_json.assert_called_once()
    sent_msg = reconnected_send_json.call_args.args[0]
    assert sent_msg["payload"] == {"hello": 1}

    grs.async_handle_message({"msgid": sent_msg["msgid"], "payload": "mock-response"})
    assert await wait_bounded(second) == "mock-response"
    assert grs._response_handler == {}
    assert grs._in_flight == set()

    await grs._async_on_disconnect()


async def test_message_timeout():
    """Test a message that never gets an answer times out."""
    grs = create_connected_grs(AsyncMock())
    await grs._async_on_connect()

    with (
        patch("hass_nabucasa.google_report_state.MESSAGE_TIMEOUT", 0.1, create=True),
        pytest.raises(ErrorResponse) as exc_info,
    ):
        await wait_bounded(grs.async_send_message({"hello": 0}))

    assert exc_info.value.code == "timeout"
    assert grs._response_handler == {}

    await grs._async_on_disconnect()


async def test_timed_out_queued_message_not_sent():
    """Test a message that timed out while queued is not sent later."""
    send_json = AsyncMock()
    grs = create_connected_grs(send_json)

    with (
        patch.object(grs, "_async_message_sender"),
        patch("hass_nabucasa.google_report_state.MESSAGE_TIMEOUT", 0.1, create=True),
        pytest.raises(ErrorResponse) as exc_info,
    ):
        await wait_bounded(grs.async_send_message({"hello": 0}))

    assert exc_info.value.code == "timeout"

    await grs._async_on_connect()
    await asyncio.sleep(0.1)

    send_json.assert_not_called()
    assert grs._to_send.empty()

    await grs._async_on_disconnect()


async def test_discard_when_oldest_message_timed_out():
    """Test a full queue discards a message whose caller already timed out."""
    grs = create_connected_grs(AsyncMock())

    for i in range(grs._to_send.maxsize):
        grs._to_send.put_nowait({"msgid": f"timed-out-{i}", "payload": {}})

    with (
        patch("hass_nabucasa.google_report_state.MESSAGE_TIMEOUT", 0.1, create=True),
        pytest.raises(ErrorResponse) as exc_info,
    ):
        await wait_bounded(grs.async_send_message({"hello": 0}))

    assert exc_info.value.code == "timeout"
