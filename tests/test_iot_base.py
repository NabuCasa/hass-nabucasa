"""Test the cloud.iot_base module."""
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock, Mock

from aiohttp import WSMsgType, client_exceptions
import pytest

from hass_nabucasa import iot_base, auth as auth_api


class MockIoT(iot_base.BaseIoT):
    """Mock class for IoT."""

    def __init__(self, cloud, require_subscription=True):
        """Initialize test IoT class."""
        super().__init__(cloud)
        self.received = []
        self._require_subscription = require_subscription

    @property
    def package_name(self) -> str:
        """Return package name for logging."""
        return __name__

    @property
    def ws_server_url(self) -> str:
        """Server to connect to."""
        return "http://example.com"

    @property
    def require_subscription(self) -> bool:
        """If the server requires a valid subscription."""
        return self._require_subscription

    def async_handle_message(self, msg) -> None:
        """Handle incoming message.

        Run all async tasks in a wrapper to log appropriately.
        """
        raise NotImplementedError


@pytest.fixture
def cloud_mock_iot(auth_cloud_mock):
    """Mock cloud class."""
    auth_cloud_mock.subscription_expired = False
    return auth_cloud_mock


async def test_cloud_getting_disconnected_by_server(
    mock_iot_client, caplog, cloud_mock_iot
):
    """Test server disconnecting instance."""
    conn = MockIoT(cloud_mock_iot)
    mock_iot_client.receive = AsyncMock(return_value=MagicMock(type=WSMsgType.CLOSING))

    with patch(
        "hass_nabucasa.iot_base.BaseIoT._wait_retry",
        side_effect=[None, asyncio.CancelledError],
    ):
        await conn.connect()

    assert "Connection closed" in caplog.text


async def test_cloud_receiving_bytes(mock_iot_client, caplog, cloud_mock_iot):
    """Test server disconnecting instance."""
    conn = MockIoT(cloud_mock_iot)
    mock_iot_client.receive = AsyncMock(return_value=MagicMock(type=WSMsgType.BINARY))

    await conn.connect()

    assert "Connection closed: Received non-Text message" in caplog.text


async def test_cloud_sending_invalid_json(mock_iot_client, caplog, cloud_mock_iot):
    """Test cloud sending invalid JSON."""
    conn = MockIoT(cloud_mock_iot)
    mock_iot_client.receive = AsyncMock(
        return_value=MagicMock(
            type=WSMsgType.TEXT, json=MagicMock(side_effect=ValueError)
        )
    )

    await conn.connect()

    assert "Connection closed: Received invalid JSON." in caplog.text


async def test_cloud_check_token_raising(mock_iot_client, caplog, cloud_mock_iot):
    """Test cloud unable to check token."""
    conn = MockIoT(cloud_mock_iot)
    cloud_mock_iot.auth.async_check_token.side_effect = auth_api.CloudError("BLA")

    await conn.connect()

    assert "Cannot connect because unable to refresh token: BLA" in caplog.text


async def test_cloud_connect_invalid_auth(mock_iot_client, caplog, cloud_mock_iot):
    """Test invalid auth detected by server."""
    conn = MockIoT(cloud_mock_iot)
    request_info = Mock(real_url="http://example.com")
    mock_iot_client.receive.side_effect = client_exceptions.WSServerHandshakeError(
        request_info=request_info, history=None, status=401
    )

    await conn.connect()

    assert "Connection closed: Invalid auth." in caplog.text


async def test_cloud_unable_to_connect(mock_iot_client, caplog, cloud_mock_iot):
    """Test unable to connect error."""
    conn = MockIoT(cloud_mock_iot)
    mock_iot_client.receive.side_effect = client_exceptions.ClientError(None, None)

    await conn.connect()

    assert "Unable to connect:" in caplog.text


async def test_cloud_random_exception(mock_iot_client, caplog, cloud_mock_iot):
    """Test random exception."""
    conn = MockIoT(cloud_mock_iot)
    mock_iot_client.receive.side_effect = Exception

    await conn.connect()

    assert "Unexpected error" in caplog.text


async def test_refresh_token_before_expiration_fails(auth_cloud_mock):
    """Test that we don't connect if token is expired."""
    auth_cloud_mock.subscription_expired = True
    conn = MockIoT(auth_cloud_mock)

    await conn.connect()

    assert len(auth_cloud_mock.auth.async_check_token.mock_calls) == 1
    assert len(auth_cloud_mock.client.mock_user) == 1


async def test_send_message_not_connected(cloud_mock_iot):
    """Test sending a message that expects no answer."""
    cloud_iot = MockIoT(cloud_mock_iot)

    with pytest.raises(iot_base.NotConnected):
        await cloud_iot.async_send_json_message({"msg": "yo"})
