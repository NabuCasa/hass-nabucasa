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

from .common import MockClient, prefilled_service_discovery_cache


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


@pytest.fixture(autouse=True)
def _skip_auto_login_initial_delay():
    """Skip the pre-loop auto-login delay so tests don't wait for real."""
    with patch("hass_nabucasa.AUTO_LOGIN_INITIAL_DELAY", 0):
        yield


@pytest.fixture
async def cl(cloud_client) -> cloud.Cloud:
    """Mock cloud client."""
    with patch(
        "hass_nabucasa.service_discovery.ServiceDiscovery.async_start_service_discovery",
        new=AsyncMock(),
    ):
        instance = cloud.Cloud(
            cloud_client,
            cloud.MODE_DEV,
            api_server="example.com",
        )
        instance.service_discovery._memory_cache = prefilled_service_discovery_cache()
        yield instance


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
    assert len(cl._on_stop) == 4
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
    assert len(cl._on_stop) == 4
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

    logout_events: list[cloud.CloudEvent] = []
    token_at_publish: list[str | None] = []

    async def on_logout(event: cloud.CloudEvent) -> None:
        logout_events.append(event)
        token_at_publish.append(cl.id_token)

    cl.events.subscribe(event_type=cloud.CloudEventType.LOGOUT, handler=on_logout)

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

    assert len(logout_events) == 1
    assert isinstance(logout_events[0], cloud.LogoutEvent)
    assert logout_events[0].type is cloud.CloudEventType.LOGOUT
    assert token_at_publish == ["id_token"]


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
    payload = {
        "cognito:username": "abc123",
        "custom:sub-exp": "2099-01-01",
        "some": "value",
    }
    encoded_token = cloud.jwt.encode(payload, key="secret")

    await cl.update_token(encoded_token, None)
    assert cl.claims == payload
    assert cl.username == "abc123"


async def test_update_token_raises_account_not_ready_without_claim(cl: cloud.Cloud):
    """Test a token without a subscription claim is refused.

    The account is not usable yet, so nothing may be stored and the instance
    must not be left half-logged-in.
    """
    token_without_claim = cloud.jwt.encode({"cognito:username": "abc"}, key="secret")

    with pytest.raises(cloud.AccountNotReady):
        await cl.update_token(
            token_without_claim,
            "test-access-token",
            "test-refresh-token",
        )

    assert cl.id_token is None
    assert cl.access_token is None
    assert cl.refresh_token is None
    assert not cl.is_logged_in


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

    with patch(
        "hass_nabucasa.wait_for_event", AsyncMock(return_value=False)
    ) as wait_mock:
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
    cl.login.assert_called_with("email@home-assistant.io", "password", auto=True)
    assert wait_mock.call_count == 1
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

    with patch("hass_nabucasa.wait_for_event", AsyncMock(return_value=False)):
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl.login.call_count == 3
    assert cl._auto_login_task is None


async def test_register_and_auto_login_retries_account_not_ready(cl: cloud.Cloud):
    """Test auto login retries while the account is still provisioning."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=[cloud.AccountNotReady(), None])

    with patch(
        "hass_nabucasa.wait_for_event", AsyncMock(return_value=False)
    ) as wait_mock:
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl.login.call_count == 2
    assert wait_mock.call_count == 1
    assert cl._auto_login_task is None


async def test_register_and_auto_login_stops_on_fatal_error(cl: cloud.Cloud):
    """Test auto login stops immediately on a non-retryable error."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=cloud.Unauthenticated("nope"))

    with patch(
        "hass_nabucasa.wait_for_event", AsyncMock(return_value=False)
    ) as wait_mock:
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl.login.call_count == 1
    assert wait_mock.call_count == 0
    assert cl._auto_login_task is None


async def test_register_and_auto_login_gives_up_after_one_day(cl: cloud.Cloud):
    """Test auto login uses tiered backoff and gives up after ~1 day."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=cloud.UserNotConfirmed())

    with patch(
        "hass_nabucasa.wait_for_event", AsyncMock(return_value=False)
    ) as wait_mock:
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    sleeps = [call.args[1] for call in wait_mock.mock_calls]

    fast_count = AUTO_LOGIN_FAST_RETRY_PERIOD // AUTO_LOGIN_FAST_RETRY_INTERVAL
    assert sleeps[:fast_count] == [AUTO_LOGIN_FAST_RETRY_INTERVAL] * fast_count

    medium_count = (
        AUTO_LOGIN_MEDIUM_RETRY_PERIOD - AUTO_LOGIN_FAST_RETRY_PERIOD
    ) // AUTO_LOGIN_MEDIUM_RETRY_INTERVAL
    assert (
        sleeps[fast_count : fast_count + medium_count]
        == [AUTO_LOGIN_MEDIUM_RETRY_INTERVAL] * medium_count
    )

    tail = sleeps[fast_count + medium_count :]
    assert tail == [
        AUTO_LOGIN_MEDIUM_RETRY_INTERVAL * 2**index for index in range(1, len(tail) + 1)
    ]

    assert sum(sleeps) <= AUTO_LOGIN_MAX_TOTAL_BACKOFF
    assert sum(sleeps) + tail[-1] * 2 > AUTO_LOGIN_MAX_TOTAL_BACKOFF
    assert cl.login.call_count == len(sleeps) + 1
    assert cl._auto_login_task is None


async def test_register_and_auto_login_handles_concurrent_login_race(cl: cloud.Cloud):
    """Test a login winning the race with async_login is treated as a no-op."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=cloud.AlreadyLoggedIn("already logged in"))

    with patch(
        "hass_nabucasa.wait_for_event", AsyncMock(return_value=False)
    ) as wait_mock:
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl.login.call_count == 1
    assert wait_mock.call_count == 0
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
    """Test the controller's cancel() stops the pending auto login."""
    cl.auth.async_register = AsyncMock()
    started = asyncio.Event()
    parked = asyncio.Event()

    async def blocking_login(*args, **kwargs):
        """Park in the first login attempt until cancelled."""
        started.set()
        await parked.wait()

    cl.login = AsyncMock(side_effect=blocking_login)

    controller = await cl.register_and_auto_login("email@home-assistant.io", "password")
    task = cl._auto_login_task
    assert task is not None

    await started.wait()
    controller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cl._auto_login_task is None
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
        patch("hass_nabucasa.wait_for_event", AsyncMock(return_value=False)),
    ):
        await cl.register_and_auto_login("email@home-assistant.io", password)
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl._auto_login_task is None
    assert all(value != password for value in vars(cl).values())
    assert password not in caplog.text


async def test_register_and_auto_login_logs_unexpected_error(
    cl: cloud.Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test an unexpected error is logged and stops the loop without escaping."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        caplog.at_level(logging.ERROR),
        patch("hass_nabucasa.wait_for_event", AsyncMock(return_value=False)),
    ):
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl.login.call_count == 1
    assert cl._auto_login_task is None
    assert "Unexpected error in auto login" in caplog.text


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


async def test_login_cancels_pending_auto_login(cl: cloud.Cloud):
    """Test a login on another path cancels a pending auto-login retry loop."""
    cl.auth.async_register = AsyncMock()
    cl.auth.async_login = AsyncMock(side_effect=[cloud.UserNotConfirmed(), None])
    attempted = asyncio.Event()

    async def park(wake, backoff):
        """Park the retry loop in the backoff wait until cancelled."""
        attempted.set()
        await asyncio.Event().wait()

    with patch("hass_nabucasa.wait_for_event", AsyncMock(side_effect=park)):
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await attempted.wait()

        await cl.login("email@home-assistant.io", "password")

    assert cl._auto_login_task is None
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cl.auth.async_login.call_count == 2


async def test_stop_cancels_pending_auto_login(cl: cloud.Cloud):
    """Test stopping the cloud cancels a pending auto-login retry loop."""
    cl._on_stop.clear()
    cl.auth.async_register = AsyncMock()
    cl.service_discovery.async_stop_service_discovery = AsyncMock()
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

    await cl.stop()

    assert cl._auto_login_task is None
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_register_and_auto_login_normalizes_email(cl: cloud.Cloud):
    """Test the email is lowercased for both registration and login."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=[cloud.UserNotConfirmed(), None])

    with patch("hass_nabucasa.wait_for_event", AsyncMock(return_value=False)):
        await cl.register_and_auto_login("User@Example.COM", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    cl.auth.async_register.assert_awaited_once_with(
        "user@example.com", "password", client_metadata=None
    )
    cl.login.assert_called_with("user@example.com", "password", auto=True)


async def test_register_and_auto_login_publishes_login_event(cl: cloud.Cloud):
    """Test a successful auto login runs the real login path and emits LOGIN."""
    cl.auth.async_register = AsyncMock()
    cl.auth.async_login = AsyncMock(side_effect=[cloud.UserNotConfirmed(), None])

    received: list[cloud.CloudEvent] = []

    async def on_event(event: cloud.CloudEvent) -> None:
        received.append(event)

    cl.events.subscribe(
        event_type=[cloud.CloudEventType.LOGIN, cloud.CloudEventType.LOGIN_FAILED],
        handler=on_event,
    )

    with patch("hass_nabucasa.wait_for_event", AsyncMock(return_value=False)):
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl.auth.async_login.call_count == 2
    assert len(received) == 1
    assert received[0].type is cloud.CloudEventType.LOGIN
    assert received[0].auto is True
    assert cl._auto_login_task is None


async def test_login_publishes_login_event_not_auto(cl: cloud.Cloud):
    """Test a manual login emits a LOGIN event flagged as not auto."""
    cl.auth.async_login = AsyncMock()

    received: list[cloud.CloudEvent] = []

    async def on_event(event: cloud.CloudEvent) -> None:
        received.append(event)

    cl.events.subscribe(event_type=cloud.CloudEventType.LOGIN, handler=on_event)

    await cl.login("email@home-assistant.io", "password")

    assert len(received) == 1
    assert received[0].type is cloud.CloudEventType.LOGIN
    assert received[0].auto is False


async def test_register_and_auto_login_publishes_failed_event_on_give_up(
    cl: cloud.Cloud,
):
    """Test giving up after the schedule is exhausted emits LOGIN_FAILED."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=cloud.UserNotConfirmed())

    received: list[cloud.CloudEvent] = []

    async def on_failed(event: cloud.CloudEvent) -> None:
        received.append(event)

    cl.events.subscribe(event_type=cloud.CloudEventType.LOGIN_FAILED, handler=on_failed)

    with patch("hass_nabucasa.wait_for_event", AsyncMock(return_value=False)):
        controller = await cl.register_and_auto_login(
            "email@home-assistant.io", "password"
        )
        task = cl._auto_login_task
        assert task is not None
        await task

    assert len(received) == 1
    assert received[0].type is cloud.CloudEventType.LOGIN_FAILED
    assert received[0].auto is True
    assert received[0].reason is cloud.LoginFailedReason.TIMEOUT
    assert controller.failed_reason is cloud.LoginFailedReason.TIMEOUT
    assert controller.active is False
    assert cl._auto_login_task is None


async def test_register_and_auto_login_publishes_failed_event_on_fatal_error(
    cl: cloud.Cloud,
):
    """Test a fatal error emits LOGIN_FAILED so the caller stops waiting."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=cloud.Unauthenticated("nope"))

    received: list[cloud.CloudEvent] = []

    async def on_failed(event: cloud.CloudEvent) -> None:
        received.append(event)

    cl.events.subscribe(event_type=cloud.CloudEventType.LOGIN_FAILED, handler=on_failed)

    with patch("hass_nabucasa.wait_for_event", AsyncMock(return_value=False)):
        controller = await cl.register_and_auto_login(
            "email@home-assistant.io", "password"
        )
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl.login.call_count == 1
    assert len(received) == 1
    assert received[0].type is cloud.CloudEventType.LOGIN_FAILED
    assert received[0].auto is True
    assert received[0].reason is cloud.LoginFailedReason.CLOUD_ERROR
    assert controller.failed_reason is cloud.LoginFailedReason.CLOUD_ERROR
    assert controller.active is False
    assert cl._auto_login_task is None


async def test_register_and_auto_login_publishes_failed_event_on_unexpected_error(
    cl: cloud.Cloud,
    caplog: pytest.LogCaptureFixture,
):
    """Test an unexpected error emits LOGIN_FAILED without escaping the task."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=RuntimeError("boom"))

    received: list[cloud.CloudEvent] = []

    async def on_failed(event: cloud.CloudEvent) -> None:
        received.append(event)

    cl.events.subscribe(event_type=cloud.CloudEventType.LOGIN_FAILED, handler=on_failed)

    with (
        caplog.at_level(logging.ERROR),
        patch("hass_nabucasa.wait_for_event", AsyncMock(return_value=False)),
    ):
        controller = await cl.register_and_auto_login(
            "email@home-assistant.io", "password"
        )
        task = cl._auto_login_task
        assert task is not None
        await task

    assert "Unexpected error in auto login" in caplog.text
    assert len(received) == 1
    assert received[0].type is cloud.CloudEventType.LOGIN_FAILED
    assert received[0].auto is True
    assert received[0].reason is cloud.LoginFailedReason.UNEXPECTED_ERROR
    assert controller.failed_reason is cloud.LoginFailedReason.UNEXPECTED_ERROR
    assert controller.active is False
    assert cl._auto_login_task is None


async def test_register_and_auto_login_no_failed_event_on_cancel(cl: cloud.Cloud):
    """Test a cancelled auto login does not emit LOGIN_FAILED."""
    cl.auth.async_register = AsyncMock()
    started = asyncio.Event()
    parked = asyncio.Event()

    async def blocking_login(*args, **kwargs):
        """Park in the first login attempt until cancelled."""
        started.set()
        await parked.wait()

    cl.login = AsyncMock(side_effect=blocking_login)

    received: list[cloud.CloudEvent] = []

    async def on_failed(event: cloud.CloudEvent) -> None:
        received.append(event)

    cl.events.subscribe(event_type=cloud.CloudEventType.LOGIN_FAILED, handler=on_failed)

    controller = await cl.register_and_auto_login("email@home-assistant.io", "password")
    task = cl._auto_login_task
    assert task is not None

    await started.wait()
    controller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert received == []
    assert controller.active is False
    assert controller.failed_reason is None
    assert cl._auto_login_task is None


async def test_register_and_auto_login_no_failed_event_on_login_race(cl: cloud.Cloud):
    """Test a login winning the race does not emit LOGIN_FAILED."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=cloud.AlreadyLoggedIn("already logged in"))

    received: list[cloud.CloudEvent] = []

    async def on_failed(event: cloud.CloudEvent) -> None:
        received.append(event)

    cl.events.subscribe(event_type=cloud.CloudEventType.LOGIN_FAILED, handler=on_failed)

    with patch("hass_nabucasa.wait_for_event", AsyncMock(return_value=False)):
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    assert cl.login.call_count == 1
    assert received == []
    assert cl._auto_login_task is None


async def test_register_and_auto_login_attempt_now(cl: cloud.Cloud):
    """Test attempt_now() forces an immediate retry instead of waiting the backoff."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(side_effect=[cloud.UserNotConfirmed(), None])

    async def wait_until_forced(wake: asyncio.Event, backoff: int) -> bool:
        """Block until an immediate attempt is requested (never time out)."""
        await wake.wait()
        wake.clear()
        return True

    with patch(
        "hass_nabucasa.wait_for_event",
        AsyncMock(side_effect=wait_until_forced),
    ):
        controller = await cl.register_and_auto_login(
            "email@home-assistant.io", "password"
        )
        task = cl._auto_login_task
        assert task is not None
        controller.attempt_now()
        await task

    assert cl.login.call_count == 2
    assert cl._auto_login_task is None


async def test_register_and_auto_login_resend_restarts_schedule(cl: cloud.Cloud):
    """Test resend() resends the confirmation email and forces an immediate retry."""
    cl.auth.async_register = AsyncMock()
    cl.auth.async_resend_email_confirm = AsyncMock()
    cl.login = AsyncMock(side_effect=[cloud.UserNotConfirmed(), None])

    async def wait_until_forced(wake: asyncio.Event, backoff: int) -> bool:
        """Block until an immediate attempt is requested (never time out)."""
        await wake.wait()
        wake.clear()
        return True

    with patch(
        "hass_nabucasa.wait_for_event",
        AsyncMock(side_effect=wait_until_forced),
    ):
        controller = await cl.register_and_auto_login(
            "email@home-assistant.io", "password"
        )
        task = cl._auto_login_task
        assert task is not None
        await controller.resend()
        await task

    cl.auth.async_resend_email_confirm.assert_awaited_once_with(
        "email@home-assistant.io"
    )
    assert cl.login.call_count == 2
    assert cl._auto_login_task is None


async def test_auto_login_controls_noop_after_completion(cl: cloud.Cloud):
    """Test the controls do not act on the retry task once it has finished."""
    cl.auth.async_register = AsyncMock()
    cl.auth.async_resend_email_confirm = AsyncMock()
    cl.login = AsyncMock(return_value=None)

    with patch("hass_nabucasa.wait_for_event", AsyncMock(return_value=False)):
        controller = await cl.register_and_auto_login(
            "email@home-assistant.io", "password"
        )
        task = cl._auto_login_task
        assert task is not None
        await task

    assert task.done()
    assert not task.cancelled()

    controller.cancel()
    controller.attempt_now()
    await controller.resend()

    assert not task.cancelled()
    cl.auth.async_resend_email_confirm.assert_awaited_once()


async def test_register_and_auto_login_delays_first_attempt(cl: cloud.Cloud):
    """Test the first login attempt is preceded by the initial delay."""
    cl.auth.async_register = AsyncMock()
    events: list = []

    async def record_login(*args, **kwargs):
        events.append("login")

    async def record_sleep(seconds):
        events.append(("sleep", seconds))

    cl.login = AsyncMock(side_effect=record_login)

    with (
        patch("hass_nabucasa.AUTO_LOGIN_INITIAL_DELAY", 42),
        patch("hass_nabucasa.asyncio.sleep", record_sleep),
    ):
        await cl.register_and_auto_login("email@home-assistant.io", "password")
        task = cl._auto_login_task
        assert task is not None
        await task

    assert events[0] == ("sleep", 42)
    assert events[1] == "login"


async def test_auto_login_cancel_guarded_while_cancelling(cl: cloud.Cloud):
    """Test cancel() does not re-request cancellation while one is in flight."""
    cl.auth.async_register = AsyncMock()
    started = asyncio.Event()

    async def park(*args, **kwargs):
        """Park in the first login attempt until cancelled."""
        started.set()
        await asyncio.Event().wait()

    cl.login = AsyncMock(side_effect=park)

    controller = await cl.register_and_auto_login("email@home-assistant.io", "password")
    task = cl._auto_login_task
    assert task is not None
    await started.wait()

    controller.cancel()
    assert task.cancelling() == 1
    controller.cancel()
    assert task.cancelling() == 1

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_register_and_auto_login_raises_when_already_logged_in(cl: cloud.Cloud):
    """Test registering while already logged in raises before registering."""
    cl.id_token = "already-logged-in"
    assert cl.is_logged_in
    cl.auth.async_register = AsyncMock()

    with pytest.raises(cloud.AlreadyLoggedIn):
        await cl.register_and_auto_login("email@home-assistant.io", "password")

    cl.auth.async_register.assert_not_called()
    assert cl._auto_login_task is None


async def test_auto_login_controller_reports_email_and_completes(cl: cloud.Cloud):
    """Test the controller exposes the email and clears state on a clean login."""
    cl.auth.async_register = AsyncMock()
    cl.login = AsyncMock(return_value=None)

    with patch("hass_nabucasa.wait_for_event", AsyncMock(return_value=False)):
        controller = await cl.register_and_auto_login(
            "Email@Home-Assistant.io", "password"
        )
        task = cl._auto_login_task
        assert task is not None
        await task

    assert controller.email == "email@home-assistant.io"
    assert controller.active is False
    assert controller.failed_reason is None
    assert cl._auto_login_task is None
