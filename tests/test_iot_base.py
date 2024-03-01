"""Test the cloud.iot_base module."""

from unittest.mock import AsyncMock, MagicMock, Mock

from aiohttp import WSMessage, WSMsgType, client_exceptions
import pytest

from hass_nabucasa import auth as auth_api, iot_base


class MockIoT(iot_base.BaseIoT):
    """Mock class for IoT."""

    def __init__(self, cloud, require_subscription=True) -> None:
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


@pytest.fixture
def cloud_mock_iot(auth_cloud_mock):
    """Mock cloud class."""
    auth_cloud_mock.subscription_expired = False
    return auth_cloud_mock


@pytest.mark.parametrize(
    "require_first_message,messages,disconnect_reason",
    [
        (
            False,
            [
                WSMessage(
                    type=WSMsgType.CLOSING,
                    data=4002,
                    extra="Another instance connected",
                ),
            ],
            iot_base.DisconnectReason(
                True,
                "Connection closed: Closed by server. "
                "Another instance connected (4002)",
            ),
        ),
        (
            True,
            [
                WSMessage(
                    type=WSMsgType.CLOSING,
                    data=4002,
                    extra="Another instance connected",
                ),
            ],
            iot_base.DisconnectReason(
                False,
                "Connection closed: Closed by server. "
                "Another instance connected (4002)",
            ),
        ),
        (
            True,
            [
                WSMessage(
                    type=WSMsgType.TEXT,
                    data='{"msgid": "1", "handler": "system"}',
                    extra=None,
                ),
                WSMessage(
                    type=WSMsgType.CLOSING,
                    data=4002,
                    extra="Another instance connected",
                ),
            ],
            iot_base.DisconnectReason(
                True,
                "Connection closed: Closed by server. "
                "Another instance connected (4002)",
            ),
        ),
    ],
)
async def test_cloud_getting_disconnected_by_server(
    mock_iot_client,
    caplog,
    cloud_mock_iot,
    require_first_message,
    messages,
    disconnect_reason,
):
    """Test server disconnecting instance."""
    conn = MockIoT(cloud_mock_iot)
    conn.mark_connected_after_first_message = require_first_message
    mock_iot_client.receive = AsyncMock(side_effect=messages)

    await conn.connect()

    assert "Connection closed" in caplog.text
    assert conn.last_disconnect_reason == disconnect_reason


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
            type=WSMsgType.TEXT,
            json=MagicMock(side_effect=ValueError),
        ),
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
        request_info=request_info,
        history=None,
        status=401,
    )

    await conn.connect()

    assert "Connection closed: Invalid auth." in caplog.text


async def test_cloud_unable_to_connect(
    cloud_mock,
    caplog,
    cloud_mock_iot,
    mock_iot_client,
):
    """Test unable to connect error."""
    conn = MockIoT(cloud_mock_iot)
    cloud_mock.websession.ws_connect.side_effect = client_exceptions.ClientError(
        "SSL Verification failed",
    )
    await conn.connect()
    assert conn.last_disconnect_reason == iot_base.DisconnectReason(
        False,
        "Unable to connect: SSL Verification failed",
    )
    assert "Unable to connect:" in caplog.text


async def test_cloud_connection_reset_exception(
    mock_iot_client,
    caplog,
    cloud_mock_iot,
):
    """Test connection reset exception."""
    conn = MockIoT(cloud_mock_iot)
    mock_iot_client.receive.side_effect = ConnectionResetError(
        "Cannot write to closing transport",
    )

    await conn.connect()

    assert conn.last_disconnect_reason == iot_base.DisconnectReason(
        False,
        "Connection closed: Cannot write to closing transport",
    )
    assert "Cannot write to closing transport" in caplog.text


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
