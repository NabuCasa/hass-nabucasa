"""Tests for Google Report State."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

from hass_nabucasa import iot_base
from hass_nabucasa.google_report_state import ErrorResponse, GoogleReportState

from .common import MockClient


async def create_grs(ws_server, server_msg_handler) -> GoogleReportState:
    """Create a grs instance."""
    client = await ws_server(server_msg_handler)
    mock_cloud = Mock(
        subscription_expired=False,
        remotestate_server="mock-report-state-url.com",
        auth=Mock(async_check_token=AsyncMock()),
        websession=Mock(ws_connect=AsyncMock(return_value=client)),
        client=Mock(spec_set=MockClient),
    )
    return GoogleReportState(mock_cloud)


async def test_ws_server_url():
    """Test generating ws server url."""
    assert (
        GoogleReportState(Mock(remotestate_server="example.com")).ws_server_url
        == "wss://example.com/v1"
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
