"""Tests for Google Report State."""
import asyncio
from unittest.mock import Mock

from hass_nabucasa import iot_base
from hass_nabucasa.google_report_state import GoogleReportState

from tests.common import mock_coro


async def create_grs(loop, ws_server, server_msg_handler) -> GoogleReportState:
    """Create a grs instance."""
    client = await ws_server(server_msg_handler)
    mock_cloud = Mock(
        run_task=loop.create_task,
        subscription_expired=False,
        google_actions_report_state_url="mock-report-state-url",
        auth=Mock(async_check_token=Mock(side_effect=mock_coro)),
        websession=Mock(ws_connect=Mock(return_value=mock_coro(client))),
    )
    return GoogleReportState(mock_cloud)


async def test_send_messages(loop, ws_server):
    """Test that we connect if we are not connected."""
    msgs = []

    async def handle_server_msg(msg):
        """handle a server msg."""
        msgs.append(msg.json())

    grs = await create_grs(loop, ws_server, handle_server_msg)
    assert grs.state == iot_base.STATE_DISCONNECTED

    # Test we can handle two simultaneous messages while disconnected
    await asyncio.gather(
        *[grs.async_send_message({"hello": 0}), grs.async_send_message({"hello": 1})]
    )
    assert grs.state == iot_base.STATE_CONNECTED

    # One per message to handle
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert sorted(msgs, key=lambda val: val["hello"]) == [{"hello": 0}, {"hello": 1}]

    await grs.disconnect()
    assert grs.state == iot_base.STATE_DISCONNECTED
    assert grs._message_sender_task is None


async def test_max_queue_message(loop, ws_server):
    """Test that we connect if we are not connected."""
    msgs = []

    async def handle_server_msg(msg):
        """handle a server msg."""
        msgs.append(msg.json())

    grs = await create_grs(loop, ws_server, handle_server_msg)

    orig_connect = grs.connect
    grs.connect = mock_coro

    # Test we can handle sending more messages than queue fits
    await asyncio.gather(*[grs.async_send_message({"hello": i}) for i in range(150)])

    loop.create_task(orig_connect())

    # One per message to handle
    for i in range(100):
        await asyncio.sleep(0)

    assert len(msgs) == 100
