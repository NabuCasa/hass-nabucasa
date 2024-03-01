"""Test the cloud component."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, Mock, PropertyMock, patch

import pytest

import hass_nabucasa as cloud
from hass_nabucasa.utils import utcnow

from .common import MockClient


def test_constructor_loads_info_from_constant(cloud_client):
    """Test non-dev mode loads info from SERVERS constant."""
    with (
        patch.dict(
            cloud.DEFAULT_VALUES,
            {
                "beer": {
                    "cognito_client_id": "test-cognito_client_id",
                    "user_pool_id": "test-user_pool_id",
                    "region": "test-region",
                },
            },
        ),
        patch.dict(
            cloud.DEFAULT_SERVERS,
            {
                "beer": {
                    "relayer": "test-relayer",
                    "accounts": "test-subscription-info-url",
                    "cloudhook": "test-cloudhook_server",
                    "alexa": "test-alexa-token-url",
                    "acme": "test-acme-directory-server",
                    "remotestate": "test-google-actions-report-state-url",
                    "account_link": "test-account-link-url",
                    "servicehandlers": "test-servicehandlers-url",
                    "thingtalk": "test-thingtalk-url",
                },
            },
        ),
    ):
        cl = cloud.Cloud(cloud_client, "beer")

    assert cl.mode == "beer"
    assert cl.cognito_client_id == "test-cognito_client_id"
    assert cl.user_pool_id == "test-user_pool_id"
    assert cl.region == "test-region"
    assert cl.relayer_server == "test-relayer"
    assert cl.accounts_server == "test-subscription-info-url"
    assert cl.cloudhook_server == "test-cloudhook_server"
    assert cl.alexa_server == "test-alexa-token-url"
    assert cl.acme_server == "test-acme-directory-server"
    assert cl.remotestate_server == "test-google-actions-report-state-url"
    assert cl.account_link_server == "test-account-link-url"
    assert cl.thingtalk_server == "test-thingtalk-url"


async def test_initialize_loads_info(cloud_client):
    """Test initialize will load info from config file.

    Also tests that on_initialized callbacks are called when initialization finishes.
    """
    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)

    assert len(cl._on_start) == 2
    cl._on_start.clear()
    assert len(cl._on_stop) == 3
    cl._on_stop.clear()

    info_file = MagicMock(
        read_text=Mock(
            return_value=json.dumps(
                {
                    "id_token": "test-id-token",
                    "access_token": "test-access-token",
                    "refresh_token": "test-refresh-token",
                },
            ),
        ),
        exists=Mock(return_value=True),
    )

    cl.iot = MagicMock()
    cl.iot.connect = AsyncMock()

    cl.remote = MagicMock()
    cl.remote.connect = AsyncMock()

    start_done_event = asyncio.Event()

    async def start_done():
        start_done_event.set()

    cl._on_start.extend([cl.iot.connect, cl.remote.connect])
    cl.register_on_initialized(start_done)

    with (
        patch(
            "hass_nabucasa.Cloud._decode_claims",
            return_value={"custom:sub-exp": "2080-01-01"},
        ),
        patch(
            "hass_nabucasa.Cloud.user_info_path",
            new_callable=PropertyMock(return_value=info_file),
        ),
        patch("hass_nabucasa.auth.CognitoAuth.async_check_token"),
    ):
        await cl.initialize()
        await start_done_event.wait()

    assert cl.id_token == "test-id-token"
    assert cl.access_token == "test-access-token"
    assert cl.refresh_token == "test-refresh-token"
    assert len(cl.iot.connect.mock_calls) == 1
    assert len(cl.remote.connect.mock_calls) == 1


async def test_initialize_loads_invalid_info(cloud_client, caplog):
    """Test initialize load invalid info from config file."""
    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)

    info_file = MagicMock(
        read_text=Mock(return_value="invalid json"),
        exists=Mock(return_value=True),
        relative_to=Mock(return_value=".cloud/production_auth.json"),
    )

    cl.iot = MagicMock()
    cl.iot.connect = AsyncMock()

    cl.remote = MagicMock()
    cl.remote.connect = AsyncMock()

    cl._on_start.extend([cl.iot.connect, cl.remote.connect])

    with (
        patch("hass_nabucasa.Cloud._decode_claims"),
        patch(
            "hass_nabucasa.Cloud.user_info_path",
            new_callable=PropertyMock(return_value=info_file),
        ),
    ):
        await cl.initialize()

    assert cl.id_token is None
    assert len(cl.iot.connect.mock_calls) == 0
    assert len(cl.remote.connect.mock_calls) == 0
    assert (
        "Error loading cloud authentication info from .cloud/production_auth.json: "
        "Expecting value: line 1 column 1 (char 0)" in caplog.text
    )


async def test_logout_clears_info(cloud_client):
    """Test logging out disconnects and removes info."""
    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)

    assert len(cl._on_start) == 2
    cl._on_start.clear()
    assert len(cl._on_stop) == 3
    cl._on_stop.clear()

    info_file = MagicMock(
        exists=Mock(return_value=True),
        unlink=Mock(return_value=True),
    )

    cl.id_token = "id_token"
    cl.access_token = "access_token"
    cl.refresh_token = "refresh_token"

    cl.iot = MagicMock()
    cl.iot.disconnect = AsyncMock()

    cl.google_report_state = MagicMock()
    cl.google_report_state.disconnect = AsyncMock()

    cl.remote = MagicMock()
    cl.remote.disconnect = AsyncMock()

    cl._on_stop.extend(
        [cl.iot.disconnect, cl.remote.disconnect, cl.google_report_state.disconnect],
    )

    with patch(
        "hass_nabucasa.Cloud.user_info_path",
        new_callable=PropertyMock(return_value=info_file),
    ):
        await cl.logout()

    assert len(cl.iot.disconnect.mock_calls) == 1
    assert len(cl.google_report_state.disconnect.mock_calls) == 1
    assert len(cl.remote.disconnect.mock_calls) == 1
    assert cl.id_token is None
    assert cl.access_token is None
    assert cl.refresh_token is None
    assert info_file.unlink.called


async def test_remove_data(cloud_client: MockClient) -> None:
    """Test removing data."""
    cloud_dir = cloud_client.base_path / ".cloud"
    cloud_dir.mkdir()
    open(cloud_dir / "unexpected_file", "w")

    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)
    await cl.remove_data()

    assert not cloud_dir.exists()


async def test_remove_data_file(cloud_client: MockClient) -> None:
    """Test removing data when .cloud is not a directory."""
    cloud_dir = cloud_client.base_path / ".cloud"
    open(cloud_dir, "w")

    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)
    await cl.remove_data()

    assert not cloud_dir.exists()


async def test_remove_data_started(cloud_client: MockClient) -> None:
    """Test removing data when cloud is started."""
    cloud_dir = cloud_client.base_path / ".cloud"
    cloud_dir.mkdir()

    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)
    cl.started = True
    with pytest.raises(ValueError, match="Cloud not stopped"):
        await cl.remove_data()

    assert cloud_dir.exists()
    cloud_dir.rmdir()


def test_write_user_info(cloud_client):
    """Test writing user info works."""
    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)

    cl.id_token = "test-id-token"
    cl.access_token = "test-access-token"
    cl.refresh_token = "test-refresh-token"

    with patch("pathlib.Path.chmod"), patch("hass_nabucasa.atomic_write") as mock_write:
        cl._write_user_info()

    mock_file = mock_write.return_value.__enter__.return_value

    assert mock_file.write.called
    data = json.loads(mock_file.write.mock_calls[0][1][0])
    assert data == {
        "access_token": "test-access-token",
        "id_token": "test-id-token",
        "refresh_token": "test-refresh-token",
    }


def test_subscription_expired(cloud_client):
    """Test subscription being expired after 3 days of expiration."""
    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)

    token_val = {"custom:sub-exp": "2017-11-13"}
    with (
        patch.object(cl, "_decode_claims", return_value=token_val),
        patch(
            "hass_nabucasa.utcnow",
            return_value=utcnow().replace(year=2017, month=11, day=13),
        ),
    ):
        assert not cl.subscription_expired

    with (
        patch.object(cl, "_decode_claims", return_value=token_val),
        patch(
            "hass_nabucasa.utcnow",
            return_value=utcnow().replace(
                year=2017,
                month=11,
                day=19,
                hour=23,
                minute=59,
                second=59,
            ),
        ),
    ):
        assert not cl.subscription_expired

    with (
        patch.object(cl, "_decode_claims", return_value=token_val),
        patch(
            "hass_nabucasa.utcnow",
            return_value=utcnow().replace(
                year=2017,
                month=11,
                day=20,
                hour=0,
                minute=0,
                second=0,
            ),
        ),
    ):
        assert cl.subscription_expired


def test_subscription_not_expired(cloud_client):
    """Test subscription not being expired."""
    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)

    token_val = {"custom:sub-exp": "2017-11-13"}
    with (
        patch.object(cl, "_decode_claims", return_value=token_val),
        patch(
            "hass_nabucasa.utcnow",
            return_value=utcnow().replace(year=2017, month=11, day=9),
        ),
    ):
        assert not cl.subscription_expired


async def test_claims_decoding(cloud_client):
    """Test decoding claims."""
    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)

    payload = {"cognito:username": "abc123", "some": "value"}
    encoded_token = cloud.jwt.encode(payload, key="secret")

    await cl.update_token(encoded_token, None)
    assert cl.claims == payload
    assert cl.username == "abc123"
