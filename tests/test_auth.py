"""Tests for the tools to communicate with the cloud."""
import asyncio
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
import pytest

from hass_nabucasa import auth as auth_api


def aws_error(code, message="Unknown", operation_name="fake_operation_name"):
    """Generate AWS error response."""
    response = {"Error": {"Code": code, "Message": message}}
    return ClientError(response, operation_name)


def test_login_invalid_auth(mock_cognito):
    """Test trying to login with invalid credentials."""
    cloud = MagicMock(is_logged_in=False)
    auth = auth_api.CognitoAuth(cloud)
    mock_cognito.authenticate.side_effect = aws_error("NotAuthorizedException")

    with pytest.raises(auth_api.Unauthenticated):
        auth.login("user", "pass")

    assert len(cloud.write_user_info.mock_calls) == 0


def test_login_user_not_found(mock_cognito):
    """Test trying to login with invalid credentials."""
    cloud = MagicMock(is_logged_in=False)
    auth = auth_api.CognitoAuth(cloud)
    mock_cognito.authenticate.side_effect = aws_error("UserNotFoundException")

    with pytest.raises(auth_api.UserNotFound):
        auth.login("user", "pass")

    assert len(cloud.write_user_info.mock_calls) == 0


def test_login_user_not_confirmed(mock_cognito):
    """Test trying to login without confirming account."""
    cloud = MagicMock(is_logged_in=False)
    auth = auth_api.CognitoAuth(cloud)
    mock_cognito.authenticate.side_effect = aws_error("UserNotConfirmedException")

    with pytest.raises(auth_api.UserNotConfirmed):
        auth.login("user", "pass")

    assert len(cloud.write_user_info.mock_calls) == 0


def test_login(mock_cognito):
    """Test trying to login without confirming account."""
    cloud = MagicMock(is_logged_in=False)
    auth = auth_api.CognitoAuth(cloud)
    mock_cognito.id_token = "test_id_token"
    mock_cognito.access_token = "test_access_token"
    mock_cognito.refresh_token = "test_refresh_token"

    auth.login("user", "pass")

    assert len(mock_cognito.authenticate.mock_calls) == 1
    assert cloud.id_token == "test_id_token"
    assert cloud.access_token == "test_access_token"
    assert cloud.refresh_token == "test_refresh_token"
    assert len(cloud.write_user_info.mock_calls) == 1


def test_register(mock_cognito, cloud_mock):
    """Test registering an account."""
    auth = auth_api.CognitoAuth(cloud_mock)
    auth.register("email@home-assistant.io", "password")
    assert len(mock_cognito.register.mock_calls) == 1
    result_user, result_password = mock_cognito.register.mock_calls[0][1]
    assert result_user == "email@home-assistant.io"
    assert result_password == "password"


def test_register_fails(mock_cognito, cloud_mock):
    """Test registering an account."""
    mock_cognito.register.side_effect = aws_error("SomeError")
    auth = auth_api.CognitoAuth(cloud_mock)
    with pytest.raises(auth_api.CloudError):
        auth.register("email@home-assistant.io", "password")


def test_resend_email_confirm(mock_cognito, cloud_mock):
    """Test starting forgot password flow."""
    auth = auth_api.CognitoAuth(cloud_mock)
    auth.resend_email_confirm("email@home-assistant.io")
    assert len(mock_cognito.client.resend_confirmation_code.mock_calls) == 1


def test_resend_email_confirm_fails(mock_cognito, cloud_mock):
    """Test failure when starting forgot password flow."""
    auth = auth_api.CognitoAuth(cloud_mock)
    mock_cognito.client.resend_confirmation_code.side_effect = aws_error("SomeError")
    with pytest.raises(auth_api.CloudError):
        auth.resend_email_confirm("email@home-assistant.io")


def test_forgot_password(mock_cognito, cloud_mock):
    """Test starting forgot password flow."""
    auth = auth_api.CognitoAuth(cloud_mock)
    auth.forgot_password("email@home-assistant.io")
    assert len(mock_cognito.initiate_forgot_password.mock_calls) == 1


def test_forgot_password_fails(mock_cognito, cloud_mock):
    """Test failure when starting forgot password flow."""
    auth = auth_api.CognitoAuth(cloud_mock)
    mock_cognito.initiate_forgot_password.side_effect = aws_error("SomeError")
    with pytest.raises(auth_api.CloudError):
        auth.forgot_password("email@home-assistant.io")


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
    assert len(cloud_mock.write_user_info.mock_calls) == 1


async def test_check_token_does_not_write_existing_token(mock_cognito, cloud_mock):
    """Test check_token won't write new token if still valid."""
    mock_cognito.check_token.return_value = False
    auth = auth_api.CognitoAuth(cloud_mock)

    await auth.async_check_token()

    assert len(mock_cognito.check_token.mock_calls) == 1
    assert cloud_mock.id_token != mock_cognito.id_token
    assert cloud_mock.access_token != mock_cognito.access_token
    assert len(cloud_mock.write_user_info.mock_calls) == 0


async def test_check_token_raises(mock_cognito, cloud_mock):
    """Test we raise correct error."""
    mock_cognito.check_token.side_effect = aws_error("SomeError")
    auth = auth_api.CognitoAuth(cloud_mock)

    with pytest.raises(auth_api.CloudError):
        await auth.async_check_token()

    assert len(mock_cognito.check_token.mock_calls) == 1
    assert cloud_mock.id_token != mock_cognito.id_token
    assert cloud_mock.access_token != mock_cognito.access_token
    assert len(cloud_mock.write_user_info.mock_calls) == 0


async def test_async_setup(cloud_mock):
    """Test async setup."""
    auth = auth_api.CognitoAuth(cloud_mock)
    assert len(cloud_mock.iot.mock_calls) == 2
    on_connect = cloud_mock.iot.mock_calls[0][1][0]
    on_disconnect = cloud_mock.iot.mock_calls[1][1][0]

    with patch("random.randint", return_value=0), patch(
        "hass_nabucasa.auth.CognitoAuth.renew_access_token"
    ) as mock_renew:
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
