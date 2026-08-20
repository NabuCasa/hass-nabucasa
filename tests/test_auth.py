"""Tests for the tools to communicate with the cloud."""

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

from botocore.exceptions import ClientError, EndpointConnectionError
from pycognito.exceptions import MFAChallengeException
import pytest

from hass_nabucasa import CloudError, auth as auth_api
from hass_nabucasa.auth.const import (
    AUTO_LOGIN_INITIAL_BACKOFF,
    AUTO_LOGIN_MAX_TOTAL_BACKOFF,
)
from tests.common import FROZEN_NOW_AS_TIMESTAMP


@pytest.fixture
def mock_cloud(cloud_mock):
    """Mock cloud."""
    cloud_mock.is_logged_in = False
    return cloud_mock


def aws_error(code, message="Unknown", operation_name="fake_operation_name"):
    """Generate AWS error response."""
    response = {"Error": {"Code": code, "Message": message}}
    return ClientError(response, operation_name)


async def test_login_invalid_auth(mock_cognito, mock_cloud):
    """Test trying to login with invalid credentials."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.authenticate.side_effect = aws_error("NotAuthorizedException")

    with pytest.raises(auth_api.Unauthenticated):
        await auth.async_login("user", "pass")

    assert len(mock_cloud.update_token.mock_calls) == 0


async def test_login_user_not_found(mock_cognito, mock_cloud):
    """Test trying to login with invalid credentials."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.authenticate.side_effect = aws_error("UserNotFoundException")

    with pytest.raises(auth_api.UserNotFound):
        await auth.async_login("user", "pass")

    assert len(mock_cloud.update_token.mock_calls) == 0


async def test_login_user_not_confirmed(mock_cognito, mock_cloud):
    """Test trying to login without confirming account."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.authenticate.side_effect = aws_error("UserNotConfirmedException")

    with pytest.raises(auth_api.UserNotConfirmed):
        await auth.async_login("user", "pass")

    assert len(mock_cloud.update_token.mock_calls) == 0


async def test_login_connection_error(mock_cognito, mock_cloud):
    """Test login raises CloudConnectionError instead of UnknownError."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.authenticate.side_effect = EndpointConnectionError(
        endpoint_url="https://cognito-idp.us-east-1.amazonaws.com/",
        error="Failed to establish a new connection: [Errno 111] Connection refused",
    )

    with pytest.raises(
        auth_api.CloudConnectionError,
        match="Connection refused",
    ):
        await auth.async_login("user", "pass")

    assert len(mock_cloud.update_token.mock_calls) == 0


async def test_login_user_mfa_required(mock_cognito, mock_cloud):
    """Test trying to login without MFA when it is required."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.authenticate.side_effect = MFAChallengeException("MFA required", {})

    with pytest.raises(auth_api.MFARequired):
        await auth.async_login("user", "pass")

    assert len(mock_cloud.update_token.mock_calls) == 0


async def test_login_user_verify_totp_invalid_code(mock_cognito, mock_cloud):
    """Test trying to login with MFA when it is required."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.respond_to_software_token_mfa_challenge.side_effect = aws_error(
        "CodeMismatchException",
    )

    with pytest.raises(auth_api.InvalidTotpCode):
        await auth.async_login_verify_totp("user", "123456", {"session": "session"})

    assert len(mock_cloud.update_token.mock_calls) == 0


async def test_login_user_verify_totp(mock_cognito, mock_cloud):
    """Test trying to login with MFA when it is required."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.id_token = "test_id_token"
    mock_cognito.access_token = "test_access_token"
    mock_cognito.refresh_token = "test_refresh_token"

    await auth.async_login_verify_totp("user", "123456", {"session": "session"})

    assert len(mock_cognito.respond_to_software_token_mfa_challenge.mock_calls) == 1
    mock_cloud.update_token.assert_called_once_with(
        "test_id_token",
        "test_access_token",
        "test_refresh_token",
    )


async def test_login(mock_cognito, mock_cloud):
    """Test trying to login without confirming account."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.id_token = "test_id_token"
    mock_cognito.access_token = "test_access_token"
    mock_cognito.refresh_token = "test_refresh_token"

    await auth.async_login("user", "pass")

    assert len(mock_cognito.authenticate.mock_calls) == 1
    mock_cloud.update_token.assert_called_once_with(
        "test_id_token",
        "test_access_token",
        "test_refresh_token",
    )


async def test_login_with_check_connection(mock_cognito, mock_cloud):
    """Test login with connection check."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.id_token = "test_id_token"
    mock_cognito.access_token = "test_access_token"
    mock_cognito.refresh_token = "test_refresh_token"

    await auth.async_login("user", "pass", check_connection=True)

    assert len(mock_cognito.authenticate.mock_calls) == 1
    mock_cloud.update_token.assert_called_once_with(
        "test_id_token",
        "test_access_token",
        "test_refresh_token",
    )


async def test_register(mock_cognito, cloud_mock):
    """Test registering an account."""
    auth = auth_api.CognitoAuth(cloud_mock)
    await auth.async_register(
        "email@home-assistant.io",
        "password",
        client_metadata={"test": "metadata"},
    )
    assert len(mock_cognito.register.mock_calls) == 1

    call = mock_cognito.register.mock_calls[0]
    result_user, result_password = call.args
    assert result_user == "email@home-assistant.io"
    assert result_password == "password"
    assert call.kwargs["client_metadata"] == {"test": "metadata"}


async def test_register_lowercase_email(mock_cognito, cloud_mock):
    """Test forcing lowercase email when registering an account."""
    auth = auth_api.CognitoAuth(cloud_mock)
    await auth.async_register("EMAIL@HOME-ASSISTANT.IO", "password")
    assert len(mock_cognito.register.mock_calls) == 1

    call = mock_cognito.register.mock_calls[0]
    result_user = call.args[0]
    assert result_user == "email@home-assistant.io"


async def test_register_fails(mock_cognito, cloud_mock):
    """Test registering an account."""
    mock_cognito.register.side_effect = aws_error("SomeError")
    auth = auth_api.CognitoAuth(cloud_mock)
    with pytest.raises(CloudError):
        await auth.async_register("email@home-assistant.io", "password")


async def test_resend_email_confirm(mock_cognito, cloud_mock):
    """Test starting forgot password flow."""
    auth = auth_api.CognitoAuth(cloud_mock)
    await auth.async_resend_email_confirm("email@home-assistant.io")
    assert len(mock_cognito.client.resend_confirmation_code.mock_calls) == 1


async def test_resend_email_confirm_fails(mock_cognito, cloud_mock):
    """Test failure when starting forgot password flow."""
    auth = auth_api.CognitoAuth(cloud_mock)
    mock_cognito.client.resend_confirmation_code.side_effect = aws_error("SomeError")
    with pytest.raises(CloudError):
        await auth.async_resend_email_confirm("email@home-assistant.io")


async def test_forgot_password(mock_cognito, cloud_mock):
    """Test starting forgot password flow."""
    auth = auth_api.CognitoAuth(cloud_mock)
    await auth.async_forgot_password("email@home-assistant.io")
    assert len(mock_cognito.initiate_forgot_password.mock_calls) == 1


async def test_forgot_password_fails(mock_cognito, cloud_mock):
    """Test failure when starting forgot password flow."""
    auth = auth_api.CognitoAuth(cloud_mock)
    mock_cognito.initiate_forgot_password.side_effect = aws_error("SomeError")
    with pytest.raises(CloudError):
        await auth.async_forgot_password("email@home-assistant.io")


async def test_check_token_writes_new_token_on_refresh(mock_cognito, cloud_mock):
    """Test check_token writes new token if refreshed."""
    auth = auth_api.CognitoAuth(cloud_mock)
    mock_cognito.check_token.return_value = True
    mock_cognito.id_token = "new id token"
    mock_cognito.access_token = "new access token"

    await auth.async_check_token()

    assert len(mock_cognito.check_token.mock_calls) == 1
    assert cloud_mock.id_token == "new id token"
    assert cloud_mock.access_token == "new access token"
    cloud_mock.update_token.assert_called_once_with("new id token", "new access token")


async def test_check_token_does_not_write_existing_token(mock_cognito, cloud_mock):
    """Test check_token won't write new token if still valid."""
    mock_cognito.check_token.return_value = False
    auth = auth_api.CognitoAuth(cloud_mock)

    await auth.async_check_token()

    assert len(mock_cognito.check_token.mock_calls) == 1
    assert cloud_mock.id_token != mock_cognito.id_token
    assert cloud_mock.access_token != mock_cognito.access_token
    assert len(cloud_mock.update_token.mock_calls) == 0


async def test_check_token_raises(mock_cognito, cloud_mock):
    """Test we raise correct error."""
    mock_cognito.renew_access_token.side_effect = aws_error("SomeError")
    auth = auth_api.CognitoAuth(cloud_mock)

    with pytest.raises(CloudError):
        await auth.async_check_token()

    assert len(mock_cognito.check_token.mock_calls) == 2
    assert cloud_mock.id_token != mock_cognito.id_token
    assert cloud_mock.access_token != mock_cognito.access_token
    assert len(cloud_mock.update_token.mock_calls) == 0


async def test_check_token_renew_times_out(mock_cognito, cloud_mock):
    """Test a stalled token renewal raises AuthTimeoutError."""
    mock_cognito.check_token.return_value = True
    mock_cognito.renew_access_token.side_effect = lambda: time.sleep(0.1)
    auth = auth_api.CognitoAuth(cloud_mock)

    with (
        patch("hass_nabucasa.auth.cognito.DEFAULT_AUTH_TIMEOUT", 0.01),
        pytest.raises(auth_api.AuthTimeoutError),
    ):
        await auth.async_check_token()

    assert len(cloud_mock.update_token.mock_calls) == 0


async def test_async_setup(cloud_mock):
    """Test async setup."""
    auth_api.CognitoAuth(cloud_mock)
    assert len(cloud_mock.iot.mock_calls) == 2
    on_connect = cloud_mock.iot.mock_calls[0][1][0]
    on_disconnect = cloud_mock.iot.mock_calls[1][1][0]

    with (
        patch("random.randint", return_value=0),
        patch("hass_nabucasa.auth.CognitoAuth.async_renew_access_token") as mock_renew,
    ):
        await on_connect()
        # Let handle token sleep once
        await asyncio.sleep(0)
        # Let handle token refresh token
        await asyncio.sleep(0)

        assert len(mock_renew.mock_calls) == 1

        await on_disconnect()

        # Make sure task is no longer being called
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(mock_renew.mock_calls) == 1


@pytest.mark.parametrize(
    "auth_mock_kwargs",
    (
        {"access_token": None},
        {"refresh_token": None},
    ),
)
async def test_guard_no_login_authenticated_cognito(auth_mock_kwargs: dict[str, None]):
    """Test that not authenticated cognito login raises."""
    auth = auth_api.CognitoAuth(MagicMock(**auth_mock_kwargs))
    with pytest.raises(auth_api.Unauthenticated):
        await auth._async_authenticated_cognito()


@pytest.mark.parametrize(
    "exp_value,random_value,expected_sleep",
    [
        [None, 2220, "37m"],
        [120, 120, "2m"],
        [121, 120, "2m"],
        [124, 120, "4s"],
        [-124, 120, "2m"],
        [7800, 60, "2h:9m"],
        [1330, 60, "21m:10s"],
    ],
)
async def test_sleep_time_calculation(
    mock_cloud,
    caplog,
    exp_value,
    random_value,
    expected_sleep,
):
    """Test sleep time calculation."""
    auth = auth_api.CognitoAuth(mock_cloud)

    with (
        patch("hass_nabucasa.auth.cognito.expiration_from_token") as mock_exp,
        patch("hass_nabucasa.auth.cognito.asyncio.sleep", AsyncMock()),
        patch(
            "hass_nabucasa.auth.cognito.CognitoAuth.async_renew_access_token",
            side_effect=asyncio.CancelledError,
        ),
        patch("random.randint") as mock_random,
    ):
        mock_exp.return_value = (
            FROZEN_NOW_AS_TIMESTAMP + exp_value if exp_value else None
        )
        mock_random.return_value = random_value

        await auth._async_handle_token_refresh()

        assert f"Sleeping for {expected_sleep} before refreshing token" in caplog.text


async def test_register_and_auto_login_logs_in_after_confirmation(
    mock_cognito,
    mock_cloud,
):
    """Test auto login retries until the account is confirmed, then logs in."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cloud.login = AsyncMock(side_effect=[auth_api.UserNotConfirmed(), None])

    with patch("hass_nabucasa.auth.cognito.asyncio.sleep", AsyncMock()) as mock_sleep:
        await auth.async_register_and_auto_login(
            "email@home-assistant.io",
            "password",
            client_metadata={"test": "metadata"},
        )
        task = auth._auto_login_task
        assert task is not None
        await task

    assert len(mock_cognito.register.mock_calls) == 1
    assert mock_cloud.login.call_count == 2
    mock_cloud.login.assert_called_with("email@home-assistant.io", "password")
    assert mock_sleep.call_count == 1
    assert auth._auto_login_task is None


async def test_register_and_auto_login_retries_transient_errors(
    mock_cognito,
    mock_cloud,
):
    """Test auto login retries transient connection and timeout errors."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cloud.login = AsyncMock(
        side_effect=[
            auth_api.CloudConnectionError(),
            auth_api.AuthTimeoutError("timeout"),
            None,
        ],
    )

    with patch("hass_nabucasa.auth.cognito.asyncio.sleep", AsyncMock()):
        await auth.async_register_and_auto_login("email@home-assistant.io", "password")
        task = auth._auto_login_task
        assert task is not None
        await task

    assert mock_cloud.login.call_count == 3
    assert auth._auto_login_task is None


async def test_register_and_auto_login_stops_on_fatal_error(
    mock_cognito,
    mock_cloud,
):
    """Test auto login stops immediately on a non-retryable error."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cloud.login = AsyncMock(side_effect=auth_api.Unauthenticated("nope"))

    with patch("hass_nabucasa.auth.cognito.asyncio.sleep", AsyncMock()) as mock_sleep:
        await auth.async_register_and_auto_login("email@home-assistant.io", "password")
        task = auth._auto_login_task
        assert task is not None
        await task

    assert mock_cloud.login.call_count == 1
    assert mock_sleep.call_count == 0
    assert auth._auto_login_task is None


async def test_register_and_auto_login_gives_up_after_one_day(
    mock_cognito,
    mock_cloud,
):
    """Test auto login backs off exponentially and gives up after ~1 day."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cloud.login = AsyncMock(side_effect=auth_api.UserNotConfirmed())

    with patch("hass_nabucasa.auth.cognito.asyncio.sleep", AsyncMock()) as mock_sleep:
        await auth.async_register_and_auto_login("email@home-assistant.io", "password")
        task = auth._auto_login_task
        assert task is not None
        await task

    sleeps = [call.args[0] for call in mock_sleep.mock_calls]
    assert sleeps
    # Delays double each time, capped at the total budget.
    for index, value in enumerate(sleeps):
        assert value == min(
            AUTO_LOGIN_INITIAL_BACKOFF * 2**index,
            AUTO_LOGIN_MAX_TOTAL_BACKOFF,
        )
    # The accumulated wait never exceeds the one-day budget...
    assert sum(sleeps) <= AUTO_LOGIN_MAX_TOTAL_BACKOFF
    # ...and it gave up because the next delay would have exceeded it.
    next_backoff = min(
        AUTO_LOGIN_INITIAL_BACKOFF * 2 ** len(sleeps),
        AUTO_LOGIN_MAX_TOTAL_BACKOFF,
    )
    assert sum(sleeps) + next_backoff > AUTO_LOGIN_MAX_TOTAL_BACKOFF
    # One final attempt happens after the last sleep, before giving up.
    assert mock_cloud.login.call_count == len(sleeps) + 1
    assert auth._auto_login_task is None


async def test_register_and_auto_login_register_failure_short_circuits(
    mock_cognito,
    mock_cloud,
):
    """Test a failed registration propagates and never starts auto login."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.register.side_effect = aws_error("UsernameExistsException")
    mock_cloud.login = AsyncMock()

    with pytest.raises(auth_api.UserExists):
        await auth.async_register_and_auto_login("email@home-assistant.io", "password")

    assert auth._auto_login_task is None
    assert mock_cloud.login.call_count == 0


async def test_cancel_auto_login(mock_cognito, mock_cloud):
    """Test cancelling a pending auto login stops the retry loop."""
    auth = auth_api.CognitoAuth(mock_cloud)
    started = asyncio.Event()
    parked = asyncio.Event()

    async def blocking_login(*args, **kwargs):
        """Park in the first login attempt until cancelled."""
        started.set()
        await parked.wait()

    mock_cloud.login = AsyncMock(side_effect=blocking_login)

    await auth.async_register_and_auto_login("email@home-assistant.io", "password")
    task = auth._auto_login_task
    assert task is not None

    await started.wait()
    auth.cancel_auto_login()

    assert auth._auto_login_task is None
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mock_cloud.login.call_count == 1


async def test_register_and_auto_login_does_not_retain_credentials(
    mock_cognito,
    mock_cloud,
    caplog,
):
    """Test credentials are never stored on the instance or logged."""
    password = "sup3r-s3cr3t-p4ssw0rd"
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cloud.login = AsyncMock(side_effect=[auth_api.UserNotConfirmed(), None])

    with (
        caplog.at_level(logging.DEBUG, logger="hass_nabucasa.auth.cognito"),
        patch("hass_nabucasa.auth.cognito.asyncio.sleep", AsyncMock()),
    ):
        await auth.async_register_and_auto_login("email@home-assistant.io", password)
        task = auth._auto_login_task
        assert task is not None
        await task

    assert auth._auto_login_task is None
    assert all(value != password for value in vars(auth).values())
    assert password not in caplog.text
