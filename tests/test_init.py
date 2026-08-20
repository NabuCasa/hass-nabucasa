"""Test the cloud component."""

import asyncio
from datetime import timedelta
import json
import logging
from unittest.mock import AsyncMock, MagicMock, Mock, PropertyMock, patch

from freezegun import freeze_time
import pytest

import hass_nabucasa as cloud
from hass_nabucasa.const import (
    AUTO_LOGIN_FAST_RETRY_INTERVAL,
    AUTO_LOGIN_FAST_RETRY_PERIOD,
    AUTO_LOGIN_MAX_TOTAL_BACKOFF,
    AUTO_LOGIN_MEDIUM_RETRY_INTERVAL,
    AUTO_LOGIN_MEDIUM_RETRY_PERIOD,
    SubscriptionReconnectionReason,
)
from hass_nabucasa.utils import utcnow

from .common import MockClient


@pytest.fixture(autouse=True)
def mock_subscription_info(aioclient_mock):
    """Mock subscription info."""
    aioclient_mock.get(
        "https://example.com/account/payments/subscription_info",
        json={
            "success": True,
            "billing_plan_type": "mock-plan",
        },
    )


@pytest.fixture
async def cl(cloud_client) -> cloud.Cloud:
    """Mock cloud client."""
    with patch(
        "hass_nabucasa.service_discovery.ServiceDiscovery.async_start_service_discovery",
        new=AsyncMock(),
    ):
        yield cloud.Cloud(
            cloud_client,
            cloud.MODE_DEV,
            api_server="example.com",
        )


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
                    "acme": "test-acme-directory-server",
                    "remotestate": "test-google-actions-report-state-url",
                    "account_link": "test-account-link-url",
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
    assert cl.acme_server == "test-acme-directory-server"
    assert cl.remotestate_server == "test-google-actions-report-state-url"
    assert cl.account_link_server == "test-account-link-url"


async def test_initialize_loads_info(cl: cloud.Cloud) -> None:
    """Test initialize will load info from config file.

    Also tests that on_initialized callbacks are called when initialization finishes.
    """
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


async def test_initialize_loads_invalid_info(
    cloud_client: MockClient,
    cl: cloud.Cloud,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test initialize load invalid info from config file."""
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
        await asyncio.sleep(0)  # Flush out scheduled callbacks

    assert cl.id_token is None
    assert len(cl.iot.connect.mock_calls) == 0
    assert len(cl.remote.connect.mock_calls) == 0
    assert (
        "Error loading cloud authentication info from .cloud/production_auth.json: "
        "Expecting value: line 1 column 1 (char 0)" in caplog.text
    )
    assert cloud_client.mock_user
    assert cloud_client.mock_user[0] == (
        "load_auth_data",
        "Home Assistant Cloud error",
        (
            "Unable to load authentication from .cloud/production_auth.json. "
            "[Please login again](/config/cloud)"
        ),
    )


async def test_logout_clears_info(cl: cloud.Cloud):
    """Test logging out disconnects and removes info."""
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


async def test_remove_data(cloud_client: MockClient, cl: cloud.Cloud) -> None:
    """Test removing data."""
    cloud_dir = cloud_client.base_path / ".cloud"
    cloud_dir.mkdir()
    open(cloud_dir / "unexpected_file", "w")

    await cl.remove_data()

    assert not cloud_dir.exists()


async def test_remove_data_file(cloud_client: MockClient, cl: cloud.Cloud) -> None:
    """Test removing data when .cloud is not a directory."""
    cloud_dir = cloud_client.base_path / ".cloud"
    open(cloud_dir, "w")

    await cl.remove_data()

    assert not cloud_dir.exists()


async def test_remove_data_started(cloud_client: MockClient, cl: cloud.Cloud) -> None:
    """Test removing data when cloud is started."""
    cloud_dir = cloud_client.base_path / ".cloud"
    cloud_dir.mkdir()

    cl.started = True
    with pytest.raises(ValueError, match="Cloud not stopped"):
        await cl.remove_data()

    assert cloud_dir.exists()
    cloud_dir.rmdir()


def test_write_user_info(cl: cloud.Cloud):
    """Test writing user info works."""
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


def test_subscription_expired(cl: cloud.Cloud):
    """Test subscription being expired after 3 days of expiration."""
    token_val = {"custom:sub-exp": "2018-09-17"}

    with (
        patch.object(cl, "_decode_claims", return_value=token_val),
    ):
        assert not cl.subscription_expired

    with (
        patch.object(cl, "_decode_claims", return_value=token_val),
        freeze_time("2018-09-23 23:59:59"),
    ):
        assert not cl.subscription_expired

    with (
        patch.object(cl, "_decode_claims", return_value=token_val),
        freeze_time("2018-09-24 00:00:01"),
    ):
        assert cl.subscription_expired


def test_subscription_not_expired(cl: cloud.Cloud):
    """Test subscription not being expired."""
    token_val = {"custom:sub-exp": "2018-09-19"}
    with (
        patch.object(cl, "_decode_claims", return_value=token_val),
    ):
        assert not cl.subscription_expired


async def test_claims_decoding(cl: cloud.Cloud):
    """Test decoding claims."""
    payload = {"cognito:username": "abc123", "some": "value"}
    encoded_token = cloud.jwt.encode(payload, key="secret")

    await cl.update_token(encoded_token, None)
    assert cl.claims == payload
    assert cl.username == "abc123"


@pytest.mark.parametrize(
    ("since_expired", "expected_sleep_hours"),
    [
        (timedelta(hours=1), 3),
        (timedelta(days=1), 12),
        (timedelta(days=8), 24),
        (timedelta(days=31), 24),
        (timedelta(days=180), 96),
    ],
)
async def test_subscription_reconnection_handler_renews_and_starts(
    cl: cloud.Cloud,
    since_expired: timedelta,
    expected_sleep_hours: int,
    caplog: pytest.LogCaptureFixture,
):
    """Test the subscription expired handler."""
    basedate = utcnow()
    _decode_claims_mocker = Mock(
        return_value={
            "custom:sub-exp": (basedate - since_expired).strftime("%Y-%m-%d")
        },
    )

    async def async_renew_access_token(*args, **kwargs):
        _decode_claims_mocker.return_value = {
            "custom:sub-exp": basedate.strftime("%Y-%m-%d"),
        }

    with (
        patch("hass_nabucasa.Cloud.initialize", AsyncMock()) as _initialize_mocker,
        patch(
            "hass_nabucasa.CognitoAuth.async_renew_access_token",
            side_effect=async_renew_access_token,
        ),
        patch("hass_nabucasa.asyncio.sleep", AsyncMock()) as sleep_mock,
        patch(
            "hass_nabucasa.Cloud._decode_claims",
            _decode_claims_mocker,
        ),
        patch(
            "hass_nabucasa.Cloud.is_logged_in",
            return_value=True,
        ),
    ):
        await cl._subscription_reconnection_handler(
            SubscriptionReconnectionReason.SUBSCRIPTION_EXPIRED
        )

    sleep_mock.assert_called_with(expected_sleep_hours * 60 * 60)
    _initialize_mocker.assert_awaited_once()
    assert "Stopping subscription reconnection handler" in caplog.text


async def test_subscription_reconnection_handler_aborts(
    cl: cloud.Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test the subscription expired handler abort."""
    basedate = utcnow()

    with (
        patch("hass_nabucasa.Cloud._start", AsyncMock()) as start_mock,
        patch("hass_nabucasa.remote.RemoteUI.start", AsyncMock()) as remote_start_mock,
        patch("hass_nabucasa.asyncio.sleep", AsyncMock()) as sleep_mock,
        patch(
            "hass_nabucasa.Cloud._decode_claims",
            return_value={
                "custom:sub-exp": (basedate - timedelta(days=450)).strftime("%Y-%m-%d")
            },
        ),
    ):
        await cl._subscription_reconnection_handler(
            SubscriptionReconnectionReason.SUBSCRIPTION_EXPIRED
        )

    sleep_mock.assert_not_awaited()
    sleep_mock.assert_not_called()
    start_mock.assert_not_awaited()
    start_mock.assert_not_called()
    remote_start_mock.assert_not_awaited()
    remote_start_mock.assert_not_called()
    assert "Stopping subscription reconnection handler" in caplog.text


async def test_subscription_reconnect_for_no_subscription(
    cl: cloud.Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test the subscription expired handler for no subscription."""
    cl._on_start.clear()
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

    def subscription_info_mock(billing_plan_type):
        return {"billing_plan_type": billing_plan_type}

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
        patch(
            "hass_nabucasa.CognitoAuth.async_renew_access_token",
        ),
        patch("hass_nabucasa.asyncio.sleep", AsyncMock()),
        patch(
            "hass_nabucasa.PaymentsApi.subscription_info",
            side_effect=[
                subscription_info_mock("no_subscription"),
                subscription_info_mock("mock-plan"),
            ],
        ),
    ):
        await cl.initialize()
        await start_done_event.wait()

    assert "No active subscription found" in caplog.text
    assert "Stopping subscription reconnection handler" in caplog.text


async def test_subscription_reconnection_handler_connection_error(
    cl: cloud.Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test the subscription reconnection handler for connection errors."""
    basedate = utcnow()

    with (
        patch("hass_nabucasa.Cloud.initialize", AsyncMock()) as _initialize_mocker,
        patch(
            "hass_nabucasa.CognitoAuth.async_renew_access_token",
            AsyncMock(),
        ),
        patch("hass_nabucasa.asyncio.sleep", AsyncMock()) as sleep_mock,
        patch(
            "hass_nabucasa.Cloud._decode_claims",
            return_value={"custom:sub-exp": basedate.strftime("%Y-%m-%d")},
        ),
        patch(
            "hass_nabucasa.Cloud.is_logged_in",
            return_value=True,
        ),
        patch("hass_nabucasa.random.uniform", return_value=0.05) as random_mock,
    ):
        await cl._subscription_reconnection_handler(
            SubscriptionReconnectionReason.CONNECTION_ERROR
        )

    random_mock.assert_called_with(0.01, 0.09)

    call_args = sleep_mock.call_args[0][0]
    assert abs(call_args - 216) < 0.1
    _initialize_mocker.assert_awaited_once()
    assert "Stopping subscription reconnection handler" in caplog.text
    assert "Could not establish connection (attempt 1)" in caplog.text
    assert "waiting 3m:36s before retrying" in caplog.text


async def test_register_and_auto_login_logs_in_after_confirmation(cl: cloud.Cloud):
    """Test auto login retries until the account is confirmed, then logs in."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=[cloud.UserNotConfirmed(), None])

    with patch("hass_nabucasa.asyncio.sleep", AsyncMock()) as sleep_mock:
        await cl.register_and_auto_login(
            "email@home-assistant.io",
            "password",
            client_metadata={"test": "metadata"},
        )
        task = cl._auto_login_task
        assert task is not None
        await task

    cl.auth.async_register.assert_awaited_once_with(
        "email@home-assistant.io", "password", client_metadata={"test": "metadata"}
    )
    assert cl.login.call_count == 2
    cl.login.assert_called_with("email@home-assistant.io", "password")
    assert sleep_mock.call_count == 1
    assert cl._auto_login_task is None


async def test_register_and_auto_login_retries_transient_errors(cl: cloud.Cloud):
    """Test auto login retries transient connection and timeout errors."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(
        side_effect=[
            cloud.CloudConnectionError(),
            cloud.AuthTimeoutError("timeout"),
            None,
        ],
    )

    with patch("hass_nabucasa.asyncio.sleep", AsyncMock()):
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl.login.call_count == 3
    assert cl._auto_login_task is None


async def test_register_and_auto_login_stops_on_fatal_error(cl: cloud.Cloud):
    """Test auto login stops immediately on a non-retryable error."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=cloud.Unauthenticated("nope"))

    with patch("hass_nabucasa.asyncio.sleep", AsyncMock()) as sleep_mock:
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl.login.call_count == 1
    assert sleep_mock.call_count == 0
    assert cl._auto_login_task is None


async def test_register_and_auto_login_gives_up_after_one_day(cl: cloud.Cloud):
    """Test auto login uses tiered backoff and gives up after ~1 day."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=cloud.UserNotConfirmed())

    with patch("hass_nabucasa.asyncio.sleep", AsyncMock()) as sleep_mock:
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    sleeps = [call.args[0] for call in sleep_mock.mock_calls]

    # Fixed 5s retries for the first minute.
    fast_count = AUTO_LOGIN_FAST_RETRY_PERIOD // AUTO_LOGIN_FAST_RETRY_INTERVAL
    assert sleeps[:fast_count] == [AUTO_LOGIN_FAST_RETRY_INTERVAL] * fast_count

    # Fixed 10s retries from 1 minute up to 5 minutes.
    medium_count = (
        AUTO_LOGIN_MEDIUM_RETRY_PERIOD - AUTO_LOGIN_FAST_RETRY_PERIOD
    ) // AUTO_LOGIN_MEDIUM_RETRY_INTERVAL
    assert (
        sleeps[fast_count : fast_count + medium_count]
        == [AUTO_LOGIN_MEDIUM_RETRY_INTERVAL] * medium_count
    )

    # Exponential doubling after 5 minutes, starting from the medium interval.
    tail = sleeps[fast_count + medium_count :]
    assert tail == [
        AUTO_LOGIN_MEDIUM_RETRY_INTERVAL * 2**index for index in range(1, len(tail) + 1)
    ]

    # The accumulated wait never exceeds the one-day budget, and it gave up
    # because the next delay would have exceeded it.
    assert sum(sleeps) <= AUTO_LOGIN_MAX_TOTAL_BACKOFF
    assert sum(sleeps) + tail[-1] * 2 > AUTO_LOGIN_MAX_TOTAL_BACKOFF
    # One final attempt happens after the last sleep, before giving up.
    assert cl.login.call_count == len(sleeps) + 1
    assert cl._auto_login_task is None


async def test_register_and_auto_login_handles_concurrent_login_race(cl: cloud.Cloud):
    """Test a login winning the race with async_login's assert is a no-op."""
    cl.auth.async_register = AsyncMock()

    async def racing_login(*args, **kwargs):
        """Simulate another task logging in just before async_login's assert."""
        cl.id_token = "token"
        raise AssertionError("Cannot login if already logged in.")

    cl.login = AsyncMock(side_effect=racing_login)

    with patch("hass_nabucasa.asyncio.sleep", AsyncMock()) as sleep_mock:
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl.login.call_count == 1
    assert sleep_mock.call_count == 0
    assert cl._auto_login_task is None


async def test_register_and_auto_login_register_failure_short_circuits(
    cl: cloud.Cloud,
):
    """Test a failed registration propagates and never starts auto login."""
    cl.auth.async_register = AsyncMock(side_effect=cloud.UserExists("exists"))
    cl.login = AsyncMock()

    with pytest.raises(cloud.UserExists):
        await cl.register_and_auto_login("email@home-assistant.io", "password")

    assert cl._auto_login_task is None
    assert cl.login.call_count == 0


async def test_cancel_auto_login(cl: cloud.Cloud):
    """Test cancelling a pending auto login stops the retry loop."""
    cl.auth.async_register = AsyncMock()
    started = asyncio.Event()
    parked = asyncio.Event()

    async def blocking_login(*args, **kwargs):
        """Park in the first login attempt until cancelled."""
        started.set()
        await parked.wait()

    cl.login = AsyncMock(side_effect=blocking_login)

    await cl.register_and_auto_login("email@home-assistant.io", "password")
    task = cl._auto_login_task
    assert task is not None

    await started.wait()
    cl.cancel_auto_login()

    assert cl._auto_login_task is None
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cl.login.call_count == 1


async def test_register_and_auto_login_does_not_retain_credentials(
    cl: cloud.Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test credentials are never stored on the instance or logged."""
    password = "sup3r-s3cr3t-p4ssw0rd"
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=[cloud.UserNotConfirmed(), None])

    with (
        caplog.at_level(logging.DEBUG),
        patch("hass_nabucasa.asyncio.sleep", AsyncMock()),
    ):
        await cl.register_and_auto_login("email@home-assistant.io", password)
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl._auto_login_task is None
    assert all(value != password for value in vars(cl).values())
    assert password not in caplog.text


async def test_register_and_auto_login_reraises_unexpected_assertion(cl: cloud.Cloud):
    """Test an assertion error while not logged in is not swallowed."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=AssertionError("boom"))

    with patch("hass_nabucasa.asyncio.sleep", AsyncMock()):
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        with pytest.raises(AssertionError, match="boom"):
            await task

    assert cl._auto_login_task is None


async def test_logout_cancels_pending_auto_login(cl: cloud.Cloud):
    """Test logging out cancels a pending auto-login retry loop."""
    cl.auth.async_register = AsyncMock()
    cl.stop = AsyncMock()
    started = asyncio.Event()
    parked = asyncio.Event()

    async def blocking_login(*args, **kwargs):
        """Park in the first login attempt until cancelled."""
        started.set()
        await parked.wait()

    cl.login = AsyncMock(side_effect=blocking_login)

    await cl.register_and_auto_login("email@home-assistant.io", "password")
    task = cl._auto_login_task
    assert task is not None
    await started.wait()

    await cl.logout()

    assert cl._auto_login_task is None
    with pytest.raises(asyncio.CancelledError):
        await task
