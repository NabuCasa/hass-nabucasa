"""Test the cloud component."""
import json
from unittest.mock import patch, MagicMock, Mock, PropertyMock

import hass_nabucasa as cloud
from hass_nabucasa.utils import utcnow

from .common import mock_coro


def test_constructor_loads_info_from_constant(cloud_client):
    """Test non-dev mode loads info from SERVERS constant."""
    with patch.dict(
        cloud.SERVERS,
        {
            "beer": {
                "cognito_client_id": "test-cognito_client_id",
                "user_pool_id": "test-user_pool_id",
                "region": "test-region",
                "relayer": "test-relayer",
                "google_actions_sync_url": "test-google_actions_sync_url",
                "subscription_info_url": "test-subscription-info-url",
                "cloudhook_create_url": "test-cloudhook_create_url",
                "remote_api_url": "test-remote_api_url",
                "alexa_access_token_url": "test-alexa-token-url",
                "acme_directory_server": "test-acme-directory-server",
                "google_actions_report_state_url": "test-google-actions-report-state-url",
                "account_link_url": "test-account-link-url",
                "voice_api_url": "test-voice-api-url",
                "thingtalk_url": "test-thingtalk-url",
            }
        },
    ):
        cl = cloud.Cloud(cloud_client, "beer")

    assert cl.mode == "beer"
    assert cl.cognito_client_id == "test-cognito_client_id"
    assert cl.user_pool_id == "test-user_pool_id"
    assert cl.region == "test-region"
    assert cl.relayer == "test-relayer"
    assert cl.google_actions_sync_url == "test-google_actions_sync_url"
    assert cl.subscription_info_url == "test-subscription-info-url"
    assert cl.cloudhook_create_url == "test-cloudhook_create_url"
    assert cl.remote_api_url == "test-remote_api_url"
    assert cl.alexa_access_token_url == "test-alexa-token-url"
    assert cl.acme_directory_server == "test-acme-directory-server"
    assert cl.google_actions_report_state_url == "test-google-actions-report-state-url"
    assert cl.account_link_url == "test-account-link-url"
    assert cl.thingtalk_url == "test-thingtalk-url"


async def test_initialize_loads_info(cloud_client):
    """Test initialize will load info from config file."""
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
                }
            )
        ),
        exists=Mock(return_value=True),
    )

    cl.iot = MagicMock()
    cl.iot.connect.return_value = mock_coro()

    cl.remote = MagicMock()
    cl.remote.connect.return_value = mock_coro()

    cl._on_start.extend([cl.iot.connect, cl.remote.connect])

    with patch("hass_nabucasa.Cloud._decode_claims"), patch(
        "hass_nabucasa.Cloud.user_info_path",
        new_callable=PropertyMock(return_value=info_file),
    ):
        await cl.start()

    assert cl.id_token == "test-id-token"
    assert cl.access_token == "test-access-token"
    assert cl.refresh_token == "test-refresh-token"
    assert len(cl.iot.connect.mock_calls) == 1
    assert len(cl.remote.connect.mock_calls) == 1


async def test_logout_clears_info(cloud_client):
    """Test logging out disconnects and removes info."""
    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)

    assert len(cl._on_start) == 2
    cl._on_start.clear()
    assert len(cl._on_stop) == 3
    cl._on_stop.clear()

    info_file = MagicMock(
        exists=Mock(return_value=True), unlink=Mock(return_value=True)
    )

    cl.id_token = "id_token"
    cl.access_token = "access_token"
    cl.refresh_token = "refresh_token"

    cl.iot = MagicMock()
    cl.iot.disconnect.return_value = mock_coro()

    cl.google_report_state = MagicMock()
    cl.google_report_state.disconnect.return_value = mock_coro()

    cl.remote = MagicMock()
    cl.remote.disconnect.return_value = mock_coro()

    cl._on_stop.extend(
        [cl.iot.disconnect, cl.remote.disconnect, cl.google_report_state.disconnect]
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


def test_write_user_info(cloud_client):
    """Test writing user info works."""
    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)

    info_file = MagicMock(
        exists=Mock(return_value=True), write_text=Mock(return_value=True)
    )

    cl.id_token = "test-id-token"
    cl.access_token = "test-access-token"
    cl.refresh_token = "test-refresh-token"

    with patch(
        "hass_nabucasa.Cloud.user_info_path",
        new_callable=PropertyMock(return_value=info_file),
    ):
        cl.write_user_info()

    assert info_file.write_text.called
    data = json.loads(info_file.write_text.mock_calls[0][1][0])
    assert data == {
        "access_token": "test-access-token",
        "id_token": "test-id-token",
        "refresh_token": "test-refresh-token",
    }


def test_subscription_expired(cloud_client):
    """Test subscription being expired after 3 days of expiration."""
    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)

    token_val = {"custom:sub-exp": "2017-11-13"}
    with patch.object(cl, "_decode_claims", return_value=token_val), patch(
        "hass_nabucasa.utcnow",
        return_value=utcnow().replace(year=2017, month=11, day=13),
    ):
        assert not cl.subscription_expired

    with patch.object(cl, "_decode_claims", return_value=token_val), patch(
        "hass_nabucasa.utcnow",
        return_value=utcnow().replace(
            year=2017, month=11, day=19, hour=23, minute=59, second=59
        ),
    ):
        assert not cl.subscription_expired

    with patch.object(cl, "_decode_claims", return_value=token_val), patch(
        "hass_nabucasa.utcnow",
        return_value=utcnow().replace(
            year=2017, month=11, day=20, hour=0, minute=0, second=0
        ),
    ):
        assert cl.subscription_expired


def test_subscription_not_expired(cloud_client):
    """Test subscription not being expired."""
    cl = cloud.Cloud(cloud_client, cloud.MODE_DEV)

    token_val = {"custom:sub-exp": "2017-11-13"}
    with patch.object(cl, "_decode_claims", return_value=token_val), patch(
        "hass_nabucasa.utcnow",
        return_value=utcnow().replace(year=2017, month=11, day=9),
    ):
        assert not cl.subscription_expired
