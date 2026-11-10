"""Tests for the tools to communicate with the cloud."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from botocore import UNSIGNED as UNSIGNED_BOTOCORE
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ProxyConnectionError,
    ReadTimeoutError,
)
from botocore.stub import Stubber
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from jwt.algorithms import RSAAlgorithm
from pycognito.exceptions import MFAChallengeException, TokenVerificationException
import pytest

from hass_nabucasa import CloudError, auth as auth_api
from hass_nabucasa.auth.cognito import _cached_cognito
from hass_nabucasa.auth.const import (
    AUTH_CONNECT_TIMEOUT,
    AUTH_RENEW_MAX_ATTEMPTS,
    AUTH_RENEW_READ_TIMEOUT,
    AUTH_USER_READ_TIMEOUT,
)
from tests.common import FROZEN_NOW_AS_TIMESTAMP

USER_POOL_URL = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test"
SIGNING_KEYS_URL = f"{USER_POOL_URL}/.well-known/jwks.json"
SIGNING_KEYS = {"keys": [{"kid": "test-kid", "kty": "RSA"}]}


@pytest.fixture
def mock_cloud(cloud_mock):
    """Mock cloud."""
    cloud_mock.is_logged_in = False
    return cloud_mock


@pytest.fixture
def mock_cognito(mock_cognito, aioclient_mock):
    """Mock a Cognito client whose signing keys can be downloaded."""
    mock_cognito.user_pool_url = USER_POOL_URL
    aioclient_mock.get(SIGNING_KEYS_URL, json=SIGNING_KEYS)
    return mock_cognito


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


@pytest.mark.parametrize(
    ("side_effect", "expected_error", "expected_message"),
    [
        (
            EndpointConnectionError(
                endpoint_url="https://example.com",
                error="Failed to establish a new connection: [Errno 111] "
                "Connection refused",
            ),
            auth_api.CloudConnectionError,
            "Connection refused",
        ),
        (
            ConnectTimeoutError(endpoint_url="https://example.com"),
            auth_api.CloudConnectionError,
            "Connect timeout",
        ),
        (
            ConnectionClosedError(endpoint_url="https://example.com"),
            auth_api.CloudConnectionError,
            "Connection was closed",
        ),
        (
            ProxyConnectionError(proxy_url="https://proxy.example.com"),
            auth_api.CloudConnectionError,
            "Failed to connect to proxy",
        ),
        (
            ReadTimeoutError(endpoint_url="https://example.com"),
            auth_api.AuthTimeoutError,
            "Read timeout",
        ),
    ],
)
async def test_login_connection_error(
    mock_cognito,
    mock_cloud,
    side_effect,
    expected_error,
    expected_message,
):
    """Test transient botocore errors map to retryable errors, not UnknownError."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.authenticate.side_effect = side_effect

    with pytest.raises(expected_error, match=expected_message):
        await auth.async_login("user", "pass")

    assert len(mock_cloud.update_token.mock_calls) == 0


async def test_login_unmapped_botocore_error(mock_cognito, mock_cloud):
    """Test an unmapped botocore error is not treated as retryable."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.authenticate.side_effect = NoCredentialsError()

    with pytest.raises(auth_api.UnknownError, match="Unable to locate credentials"):
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


async def test_login_account_not_ready(mock_cognito, mock_cloud):
    """Test login surfaces AccountNotReady instead of swallowing it."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.id_token = "test_id_token"
    mock_cognito.access_token = "test_access_token"
    mock_cognito.refresh_token = "test_refresh_token"
    mock_cloud.update_token.side_effect = auth_api.AccountNotReady

    with pytest.raises(auth_api.AccountNotReady):
        await auth.async_login("user", "pass")


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


async def test_register_presignup_already_exists_maps_to_user_exists(
    mock_cognito,
    cloud_mock,
):
    """Test a PreSignUp Lambda "already exists" error maps to UserExists.

    Cognito wraps it as a generic UserLambdaValidationException, not the plain
    UsernameExistsException, so it must not leak as an UnknownError, and the
    internal "PreSignUp failed with error ||" wrapper must be stripped.
    """
    mock_cognito.register.side_effect = aws_error(
        "UserLambdaValidationException",
        "PreSignUp failed with error ||An account for this email already exists.",
    )
    auth = auth_api.CognitoAuth(cloud_mock)
    with pytest.raises(auth_api.UserExists) as err:
        await auth.async_register("email@home-assistant.io", "password")

    assert str(err.value) == "An account for this email already exists."


async def test_register_other_lambda_validation_strips_wrapper(
    mock_cognito,
    cloud_mock,
):
    """Test an unrelated Lambda validation error keeps only the clean message."""
    mock_cognito.register.side_effect = aws_error(
        "UserLambdaValidationException",
        "PreSignUp failed with error ||Sign ups are disabled.",
    )
    auth = auth_api.CognitoAuth(cloud_mock)
    with pytest.raises(auth_api.UnknownError) as err:
        await auth.async_register("email@home-assistant.io", "password")

    assert str(err.value) == "Sign ups are disabled."


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
        patch("hass_nabucasa.auth.cognito.AUTH_RENEW_TIMEOUT", 0.01),
        pytest.raises(auth_api.AuthTimeoutError),
    ):
        await auth.async_check_token()

    assert len(cloud_mock.update_token.mock_calls) == 0


async def test_login_times_out(mock_cognito, mock_cloud):
    """Test a stalled login raises AuthTimeoutError."""
    mock_cognito.authenticate.side_effect = lambda **_: time.sleep(0.1)
    auth = auth_api.CognitoAuth(mock_cloud)

    with (
        patch("hass_nabucasa.auth.cognito.AUTH_USER_TIMEOUT", 0.01),
        pytest.raises(auth_api.AuthTimeoutError),
    ):
        await auth.async_login("user", "pass")

    assert len(mock_cloud.update_token.mock_calls) == 0


async def test_login_verify_totp_times_out(mock_cognito, mock_cloud):
    """Test a stalled TOTP verification raises AuthTimeoutError."""
    mock_cognito.respond_to_software_token_mfa_challenge.side_effect = lambda **_: (
        time.sleep(0.1)
    )
    auth = auth_api.CognitoAuth(mock_cloud)

    with (
        patch("hass_nabucasa.auth.cognito.AUTH_USER_TIMEOUT", 0.01),
        pytest.raises(auth_api.AuthTimeoutError),
    ):
        await auth.async_login_verify_totp("user", "123456", {"session": "session"})

    assert len(mock_cloud.update_token.mock_calls) == 0


async def test_renew_access_token_read_timeout(mock_cognito, cloud_mock):
    """Test a read timeout while renewing the token raises AuthTimeoutError."""
    mock_cognito.renew_access_token.side_effect = ReadTimeoutError(
        endpoint_url="https://example.com",
    )
    auth = auth_api.CognitoAuth(cloud_mock)

    with pytest.raises(auth_api.AuthTimeoutError, match="Read timeout"):
        await auth.async_renew_access_token()

    assert len(cloud_mock.update_token.mock_calls) == 0


async def test_signing_keys_downloaded_once(mock_cognito, mock_cloud, aioclient_mock):
    """Test the signing keys are downloaded once and given to every Cognito call."""
    auth = auth_api.CognitoAuth(mock_cloud)
    keys_at_call = []

    def record_keys(*_, **__):
        keys_at_call.append(mock_cognito.pool_jwk)

    mock_cognito.authenticate.side_effect = record_keys
    mock_cognito.respond_to_software_token_mfa_challenge.side_effect = record_keys
    mock_cognito.renew_access_token.side_effect = record_keys

    await auth.async_login("user", "pass")
    await auth.async_login_verify_totp("user", "123456", {"session": "session"})
    await auth.async_renew_access_token()

    assert keys_at_call == [SIGNING_KEYS] * 3
    assert aioclient_mock.call_count == 1


async def test_signing_keys_refreshed_on_unknown_key(
    mock_cognito,
    mock_cloud,
    aioclient_mock,
):
    """Test an unknown signing key refreshes the keys and repeats the renewal."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.renew_access_token.side_effect = [
        auth_api.cognito.UnknownSigningKey("new-kid"),
        None,
    ]

    await auth.async_renew_access_token()

    assert aioclient_mock.call_count == 2
    assert len(mock_cognito.renew_access_token.mock_calls) == 2
    assert len(mock_cloud.update_token.mock_calls) == 1


async def test_signing_keys_refresh_fails(mock_cognito, mock_cloud, aioclient_mock):
    """Test an unknown signing key after a refresh raises UnknownSigningKey."""
    auth = auth_api.CognitoAuth(mock_cloud)
    mock_cognito.renew_access_token.side_effect = auth_api.cognito.UnknownSigningKey(
        "new-kid"
    )

    with pytest.raises(auth_api.cognito.UnknownSigningKey):
        await auth.async_renew_access_token()

    assert aioclient_mock.call_count == 2
    assert len(mock_cognito.renew_access_token.mock_calls) == 2
    assert len(mock_cloud.update_token.mock_calls) == 0


@pytest.mark.parametrize(
    ("method", "flow"),
    [
        ("authenticate", lambda auth: auth.async_login("user", "pass")),
        (
            "respond_to_software_token_mfa_challenge",
            lambda auth: auth.async_login_verify_totp(
                "user", "123456", {"session": "session"}
            ),
        ),
    ],
    ids=["login", "verify_totp"],
)
async def test_unknown_signing_key_not_repeated(
    mock_cognito,
    mock_cloud,
    aioclient_mock,
    method,
    flow,
):
    """Test login and TOTP aren't repeated, but the next attempt gets new keys."""
    auth = auth_api.CognitoAuth(mock_cloud)
    getattr(mock_cognito, method).side_effect = [
        auth_api.cognito.UnknownSigningKey("new-kid"),
        None,
    ]

    with pytest.raises(auth_api.cognito.UnknownSigningKey):
        await flow(auth)

    assert len(getattr(mock_cognito, method).mock_calls) == 1
    assert aioclient_mock.call_count == 1

    await flow(auth)

    assert aioclient_mock.call_count == 2


@pytest.mark.parametrize(
    "response",
    [
        {"status": 500},
        {"exc": aiohttp.ClientError("boom")},
        {"text": "not json"},
        {"json": []},
        {"json": {}},
        {"json": {"keys": None}},
        {"json": {"keys": ["not an object"]}},
    ],
    ids=[
        "server_error",
        "connection_error",
        "invalid_json",
        "not_an_object",
        "no_keys",
        "keys_null",
        "key_not_an_object",
    ],
)
async def test_signing_keys_download_error(
    mock_cognito,
    mock_cloud,
    aioclient_mock,
    response,
):
    """Test a failed signing key download raises CloudConnectionError."""
    auth = auth_api.CognitoAuth(mock_cloud)
    aioclient_mock.clear_requests()
    aioclient_mock.get(SIGNING_KEYS_URL, **response)

    with pytest.raises(
        auth_api.CloudConnectionError, match="Unable to download signing keys"
    ):
        await auth.async_login("user", "pass")

    assert len(mock_cognito.authenticate.mock_calls) == 0
    assert len(mock_cloud.update_token.mock_calls) == 0


async def test_signing_keys_not_cached_when_malformed(
    mock_cognito,
    mock_cloud,
    aioclient_mock,
):
    """Test a malformed key download isn't cached, so a later attempt recovers."""
    auth = auth_api.CognitoAuth(mock_cloud)
    aioclient_mock.clear_requests()
    aioclient_mock.get(SIGNING_KEYS_URL, json={"keys": None})

    with pytest.raises(auth_api.CloudConnectionError):
        await auth.async_login("user", "pass")

    aioclient_mock.clear_requests()
    aioclient_mock.get(SIGNING_KEYS_URL, json=SIGNING_KEYS)

    await auth.async_login("user", "pass")

    assert len(mock_cognito.authenticate.mock_calls) == 1
    assert mock_cognito.pool_jwk == SIGNING_KEYS


def test_get_key():
    """Test the Cognito client reports tokens signed with an unknown key."""
    cognito = auth_api.cognito._Cognito(
        user_pool_id="us-east-1_test",
        client_id="test-client-id",
        botocore_config=auth_api.cognito._USER_BOTOCORE_CONFIG,
    )
    cognito.pool_jwk = SIGNING_KEYS

    assert cognito.get_key("test-kid") == SIGNING_KEYS["keys"][0]
    with pytest.raises(auth_api.cognito.UnknownSigningKey):
        cognito.get_key("other-kid")

    cognito.pool_jwk = {"unexpected": "shape"}
    with pytest.raises(auth_api.cognito.UnknownSigningKey):
        cognito.get_key("test-kid")


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


@pytest.fixture
def cognito_cloud(cloud_mock):
    """Cloud mock with the settings needed to build a real Cognito client."""
    cloud_mock.user_pool_id = "us-east-1_abc123"
    cloud_mock.cognito_client_id = "cognito_client_id"
    cloud_mock.region = "us-east-1"
    _cached_cognito.cache_clear()
    yield cloud_mock
    _cached_cognito.cache_clear()


async def test_user_cognito_client_botocore_config(cognito_cloud):
    """Test the user cognito client sends each request once."""
    auth = auth_api.CognitoAuth(cognito_cloud)

    cognito = auth._create_cognito_client(username="user")

    config = cognito.client.meta.config
    assert config.signature_version is UNSIGNED_BOTOCORE
    assert config.connect_timeout == AUTH_CONNECT_TIMEOUT
    assert config.read_timeout == AUTH_USER_READ_TIMEOUT
    assert config.retries["total_max_attempts"] == 1


async def test_authenticated_cognito_client_botocore_config(cognito_cloud):
    """Test the authenticated cognito client retries token renewals."""
    cognito_cloud.access_token = "access_token"
    cognito_cloud.refresh_token = "refresh_token"
    auth = auth_api.CognitoAuth(cognito_cloud)

    cognito = await auth._async_authenticated_cognito()

    config = cognito.client.meta.config
    assert config.signature_version is UNSIGNED_BOTOCORE
    assert config.connect_timeout == AUTH_CONNECT_TIMEOUT
    assert config.read_timeout == AUTH_RENEW_READ_TIMEOUT
    assert config.retries["total_max_attempts"] == AUTH_RENEW_MAX_ATTEMPTS
    assert config.retries["mode"] == "standard"


def _rsa_key():
    """Return a new RSA private key."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(key, kid):
    """Return a JWKS with the public part of an RSA key."""
    jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": kid, "alg": "RS256", "use": "sig"}]}


def _authentication_result(key, kid, cognito):
    """Return a Cognito authentication result with tokens signed by a key."""
    claims = {"iss": cognito.user_pool_url, "exp": FROZEN_NOW_AS_TIMESTAMP + 3600}
    headers = {"kid": kid}
    return {
        "AuthenticationResult": {
            "AccessToken": jwt.encode(
                {**claims, "token_use": "access"},
                key,
                algorithm="RS256",
                headers=headers,
            ),
            "IdToken": jwt.encode(
                {**claims, "token_use": "id", "aud": cognito.client_id},
                key,
                algorithm="RS256",
                headers=headers,
            ),
            "TokenType": "Bearer",
        }
    }


async def _renewal_cognito(auth, cloud):
    """Return the real Cognito client a token renewal uses."""
    cloud.access_token = "access-token"
    cloud.refresh_token = "refresh-token"
    return await auth._async_authenticated_cognito()


async def test_renew_verifies_signed_tokens(cognito_cloud, aioclient_mock):
    """Test a renewal verifies the tokens with the downloaded signing keys."""
    auth = auth_api.CognitoAuth(cognito_cloud)
    cognito = await _renewal_cognito(auth, cognito_cloud)
    key = _rsa_key()
    aioclient_mock.get(
        f"{cognito.user_pool_url}/.well-known/jwks.json", json=_jwks(key, "kid-a")
    )
    result = _authentication_result(key, "kid-a", cognito)

    with Stubber(cognito.client) as stubber:
        stubber.add_response("initiate_auth", result)
        await auth.async_renew_access_token()

    assert aioclient_mock.call_count == 1
    cognito_cloud.update_token.assert_called_once_with(
        result["AuthenticationResult"]["IdToken"],
        result["AuthenticationResult"]["AccessToken"],
    )


async def test_renew_rejects_invalid_signature(cognito_cloud, aioclient_mock):
    """Test a renewal rejects tokens that the signing key didn't sign."""
    auth = auth_api.CognitoAuth(cognito_cloud)
    cognito = await _renewal_cognito(auth, cognito_cloud)
    aioclient_mock.get(
        f"{cognito.user_pool_url}/.well-known/jwks.json",
        json=_jwks(_rsa_key(), "kid-a"),
    )

    with Stubber(cognito.client) as stubber:
        stubber.add_response(
            "initiate_auth", _authentication_result(_rsa_key(), "kid-a", cognito)
        )
        with pytest.raises(TokenVerificationException):
            await auth.async_renew_access_token()

    assert len(cognito_cloud.update_token.mock_calls) == 0


async def test_renew_after_key_rotation(cognito_cloud, aioclient_mock):
    """Test a renewal downloads new signing keys after Cognito replaced them."""
    auth = auth_api.CognitoAuth(cognito_cloud)
    cognito = await _renewal_cognito(auth, cognito_cloud)
    auth._signing_keys = _jwks(_rsa_key(), "kid-old")
    new_key = _rsa_key()
    aioclient_mock.get(
        f"{cognito.user_pool_url}/.well-known/jwks.json",
        json=_jwks(new_key, "kid-new"),
    )
    result = _authentication_result(new_key, "kid-new", cognito)

    with Stubber(cognito.client) as stubber:
        stubber.add_response("initiate_auth", result)
        stubber.add_response("initiate_auth", result)
        await auth.async_renew_access_token()
        stubber.assert_no_pending_responses()

    assert aioclient_mock.call_count == 1
    cognito_cloud.update_token.assert_called_once_with(
        result["AuthenticationResult"]["IdToken"],
        result["AuthenticationResult"]["AccessToken"],
    )


async def test_create_cognito_client_is_cached(mock_cloud):
    """Test identical Cognito client requests reuse one client."""
    auth = auth_api.CognitoAuth(mock_cloud)
    auth_api.cognito._cached_cognito.cache_clear()

    try:
        with patch(
            "hass_nabucasa.auth.cognito._Cognito", side_effect=lambda **_: MagicMock()
        ) as cls:
            first = auth._create_cognito_client(access_token="one")  # noqa: S106
            again = auth._create_cognito_client(access_token="one")  # noqa: S106
            other = auth._create_cognito_client(access_token="two")  # noqa: S106
    finally:
        auth_api.cognito._cached_cognito.cache_clear()

    assert again is first
    assert other is not first
    assert cls.call_count == 2
