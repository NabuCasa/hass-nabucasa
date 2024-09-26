"""Tests for the tools to communicate with the cloud."""

import asyncio
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
import pytest

from hass_nabucasa import auth as auth_api


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
    with pytest.raises(auth_api.CloudError):
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
    with pytest.raises(auth_api.CloudError):
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
    with pytest.raises(auth_api.CloudError):
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

    with pytest.raises(auth_api.CloudError):
        await auth.async_check_token()

    assert len(mock_cognito.check_token.mock_calls) == 2
    assert cloud_mock.id_token != mock_cognito.id_token
    assert cloud_mock.access_token != mock_cognito.access_token
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
