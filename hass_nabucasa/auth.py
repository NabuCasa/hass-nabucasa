"""Package to communicate with the authentication API."""

from __future__ import annotations

import asyncio
import base64
from functools import lru_cache, partial
import hashlib
import hmac
import logging
import random
from typing import TYPE_CHECKING, Any, cast

import async_timeout
import boto3
import botocore
from botocore.exceptions import BotoCoreError, ClientError

from .const import MESSAGE_AUTH_FAIL
from .utils import expiration_from_token, utcnow

if TYPE_CHECKING:
    from mypy_boto3_cognito_idp.type_defs import AuthenticationResultTypeTypeDef

    from . import Cloud, _ClientT

_LOGGER = logging.getLogger(__name__)


class CloudError(Exception):
    """Exception raised for errors related to the cloud service."""


class NabucasaAuthError(CloudError):
    """Base class for all Nabucasa authentication exceptions."""


class MFAChallengeError(NabucasaAuthError):
    """Raised when MFA challenge is required."""

    def __init__(self, message: str, mfa_tokens: dict[str, Any]) -> None:
        """Initialize MFA challenge exception."""
        super().__init__(message)
        self._mfa_tokens = mfa_tokens

    def get_tokens(self) -> dict[str, Any]:
        """Return MFA tokens."""
        return self._mfa_tokens


class ForceChangePasswordError(NabucasaAuthError):
    """Raised when password change is required."""


class Unauthenticated(NabucasaAuthError):
    """Raised when authentication failed."""


class MFARequired(NabucasaAuthError):
    """Raised when MFA is required."""

    _mfa_tokens: dict[str, Any]

    def __init__(self, mfa_tokens: dict[str, Any]) -> None:
        """Initialize MFA required error."""
        super().__init__("MFA required.")
        self._mfa_tokens = mfa_tokens

    @property
    def mfa_tokens(self) -> dict[str, Any]:
        """Return MFA tokens."""
        return self._mfa_tokens


class InvalidTotpCode(CloudError):
    """Raised when the TOTP code is invalid."""


class UserNotFound(CloudError):
    """Raised when a user is not found."""


class UserExists(CloudError):
    """Raised when a username already exists."""


class UserNotConfirmed(CloudError):
    """Raised when a user has not confirmed email yet."""


class PasswordChangeRequired(CloudError):
    """Raised when a password change is required."""

    # https://github.com/PyCQA/pylint/issues/1085
    # pylint: disable=useless-super-delegation
    def __init__(self, message: str = "Password change required.") -> None:
        """Initialize a password change required error."""
        super().__init__(message)


class UnknownError(CloudError):
    """Raised when an unknown error occurs."""


class CognitoAuthClient:
    """Auth client for interacting with AWS Cognito."""

    def __init__(
        self,
        *,
        user_pool_id: str,
        client_id: str,
        user_pool_region: str,
        botocore_config: Any,
        session: boto3.Session,
        username: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        id_token: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        """Initialize the Cognito client."""
        self.user_pool_id = user_pool_id
        self.client_id = client_id
        self.user_pool_region = user_pool_region
        self.username = username
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.id_token = id_token
        self.client_secret = client_secret

        self.client = session.client(
            "cognito-idp",
            region_name=user_pool_region,
            config=botocore_config,
        )

    def _calculate_secret_hash(self, username: str) -> str:
        """Calculate the secret hash for Cognito.

        The secret hash is required when the Cognito User Pool App client
        has been configured with a client secret. It's an HMAC-SHA256
        hash of the username + client_id using the client secret as the key.
        """
        if not self.client_secret:
            return ""

        message = username + self.client_id
        secret_hash = hmac.new(
            self.client_secret.encode(), message.encode(), hashlib.sha256
        ).digest()
        return base64.b64encode(secret_hash).decode()

    def _add_secret_hash_if_needed(self, params: dict[str, Any], username: str) -> None:
        """Add secret hash to parameters if needed."""
        if secret_hash := self._calculate_secret_hash(username):
            params["SECRET_HASH"] = secret_hash

    def _add_secret_hash_to_dict_if_needed(self, username: str) -> dict[str, str]:
        """Return dict with SecretHash if needed, empty dict otherwise."""
        if secret_hash := self._calculate_secret_hash(username):
            return {"SecretHash": secret_hash}
        return {}

    def _extract_tokens_from_auth_result(
        self, auth_result: AuthenticationResultTypeTypeDef
    ) -> None:
        """Extract and store tokens from authentication result."""
        self.access_token = auth_result["AccessToken"]
        self.refresh_token = auth_result.get("RefreshToken")
        self.id_token = auth_result.get("IdToken")

    def authenticate(self, password: str) -> None:
        """Authenticate user with username and password."""
        if not self.username:
            raise ValueError("Username is required for authentication")

        try:
            auth_params = {
                "USERNAME": self.username,
                "PASSWORD": password,
            }

            # Add secret hash if needed
            self._add_secret_hash_if_needed(auth_params, self.username)

            response = self.client.initiate_auth(
                ClientId=self.client_id,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters=auth_params,
            )

            match response.get("ChallengeName"):
                case "SOFTWARE_TOKEN_MFA":
                    # MFA challenge required
                    raise MFAChallengeError(
                        "MFA challenge required",
                        mfa_tokens={
                            "Session": response["Session"],
                            "ChallengeName": response["ChallengeName"],
                            "ChallengeParameters": response.get(
                                "ChallengeParameters", {}
                            ),
                        },
                    )
                case "NEW_PASSWORD_REQUIRED":
                    # Password change required
                    raise ForceChangePasswordError("Password change required")

            # Successful authentication
            self._extract_tokens_from_auth_result(response["AuthenticationResult"])

        except ClientError as err:
            match err.response["Error"]["Code"]:
                case "NewPasswordRequiredException":
                    raise ForceChangePasswordError("Password change required") from err
                case _:
                    raise

    def respond_to_software_token_mfa_challenge(
        self, code: str, mfa_tokens: dict[str, Any]
    ) -> None:
        """Respond to software token MFA challenge."""
        challenge_params: dict[str, str] = {
            "USERNAME": self.username or "",
            "SOFTWARE_TOKEN_MFA_CODE": code,
        }

        # Add secret hash if needed
        self._add_secret_hash_if_needed(challenge_params, self.username or "")

        response = self.client.respond_to_auth_challenge(
            ClientId=self.client_id,
            ChallengeName=mfa_tokens["ChallengeName"],
            Session=mfa_tokens["Session"],
            ChallengeResponses=challenge_params,
        )

        # Extract tokens from successful response
        self._extract_tokens_from_auth_result(response["AuthenticationResult"])

    def validate_and_renew_token(self, renew: bool = True) -> bool:
        """Validate the access token and optionally renew if invalid."""
        if not self.access_token:
            return False

        try:
            # Try to get user info to validate token
            self.client.get_user(AccessToken=self.access_token)
        except ClientError:
            if renew and self.refresh_token:
                # Try to renew the token - exceptions will propagate up
                self.renew_access_token()
                return True
            return False
        return True

    def renew_access_token(self) -> None:
        """Renew the access token using refresh token."""
        if not self.refresh_token:
            raise ValueError("Refresh token is required")

        auth_params = {
            "REFRESH_TOKEN": self.refresh_token,
        }

        # Add secret hash if needed
        if self.username:
            self._add_secret_hash_if_needed(auth_params, self.username)

        response = self.client.initiate_auth(
            ClientId=self.client_id,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters=auth_params,
        )

        auth_result = response["AuthenticationResult"]
        self.access_token = auth_result["AccessToken"]
        self.id_token = auth_result.get("IdToken")
        # Refresh token might be rotated
        if refresh_token := auth_result.get("RefreshToken"):
            self.refresh_token = refresh_token

    def register(
        self,
        username: str,
        password: str,
        client_metadata: dict[str, str] | None = None,
    ) -> None:
        """Register a new user."""
        # Add secret hash if needed
        secret_hash_dict = self._add_secret_hash_to_dict_if_needed(username)

        kwargs: dict[str, Any] = {}
        if client_metadata:
            kwargs["ClientMetadata"] = client_metadata
        if secret_hash_dict and "SecretHash" in secret_hash_dict:
            kwargs["SecretHash"] = secret_hash_dict["SecretHash"]

        self.client.sign_up(
            ClientId=self.client_id,
            Username=username,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": username}],
            **kwargs,
        )

    def initiate_forgot_password(self) -> None:
        """Initiate forgot password flow."""
        if not self.username:
            raise ValueError("Username is required")

        # Add secret hash if needed
        secret_hash_dict = self._add_secret_hash_to_dict_if_needed(self.username)

        kwargs: dict[str, Any] = {}
        if secret_hash_dict and "SecretHash" in secret_hash_dict:
            kwargs["SecretHash"] = secret_hash_dict["SecretHash"]

        self.client.forgot_password(
            ClientId=self.client_id,
            Username=self.username,
            **kwargs,
        )


class CognitoAuth:
    """Handle cloud auth."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Configure the auth api."""
        self.cloud = cloud
        self._refresh_task: asyncio.Task | None = None
        self._session: boto3.Session | None = None
        self._request_lock = asyncio.Lock()

        cloud.iot.register_on_connect(self.on_connect)
        cloud.iot.register_on_disconnect(self.on_disconnect)

    def _handle_cognito_operation(self, operation_func: Any) -> Any:
        """Handle a cognito operation with common exception handling."""

        async def wrapper() -> None:
            try:
                async with self._request_lock:
                    await operation_func()
            except ClientError as err:
                raise _map_aws_exception(err) from err
            except BotoCoreError as err:
                raise UnknownError from err

        return wrapper()

    async def _async_handle_token_refresh(self) -> None:
        """Handle Cloud access token refresh."""

        def _sleep_time() -> int:
            """Generate token refresh sleep time."""
            if expiration_time := expiration_from_token(self.cloud.access_token):
                seconds_left = expiration_time - int(utcnow().timestamp())
                if (suggestion := seconds_left - random.randint(10, 610)) > 1:
                    return suggestion

            # If we don't have a valid token, or it is about to expire,
            # refresh it in a random time between 40 minutes and 1 hour.
            return random.randint(2400, 3600)

        while True:
            try:
                sleep_time = _sleep_time()
                _LOGGER.debug(
                    "Sleeping for %d seconds before refreshing token", sleep_time
                )
                await asyncio.sleep(sleep_time)
                await self.async_renew_access_token()
            except CloudError as err:
                _LOGGER.error("Can't refresh cloud token: %s", err)
            except asyncio.CancelledError:
                # Task is canceled, stop it.
                break

    async def on_connect(self) -> None:
        """When the instance is connected."""
        self._refresh_task = asyncio.create_task(self._async_handle_token_refresh())

    async def on_disconnect(self) -> None:
        """When the instance is disconnected."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()

    async def async_register(
        self,
        email: str,
        password: str,
        *,
        client_metadata: Any | None = None,
    ) -> None:
        """Register a new account."""

        async def _operation() -> None:
            cognito = await self.cloud.run_executor(
                self._create_cognito_client,
            )
            await self.cloud.run_executor(
                partial(
                    cognito.register,
                    email.lower(),
                    password,
                    client_metadata=client_metadata,
                ),
            )

        await self._handle_cognito_operation(_operation)

    async def async_resend_email_confirm(self, email: str) -> None:
        """Resend email confirmation."""

        async def _operation() -> None:
            cognito = await self.cloud.run_executor(
                partial(self._create_cognito_client, username=email),
            )
            await self.cloud.run_executor(
                partial(
                    cognito.client.resend_confirmation_code,
                    Username=email,
                    ClientId=cognito.client_id,
                ),
            )

        await self._handle_cognito_operation(_operation)

    async def async_forgot_password(self, email: str) -> None:
        """Initialize forgotten password flow."""

        async def _operation() -> None:
            cognito = await self.cloud.run_executor(
                partial(self._create_cognito_client, username=email),
            )
            await self.cloud.run_executor(cognito.initiate_forgot_password)

        await self._handle_cognito_operation(_operation)

    async def _handle_successful_authentication(
        self, cognito: CognitoAuthClient, check_connection: bool = False
    ) -> None:
        """Handle common post-authentication tasks."""
        # After successful authentication, tokens should be available
        assert cognito.access_token is not None, (
            "Access token should be available after authentication"
        )
        assert cognito.id_token is not None, (
            "ID token should be available after authentication"
        )

        if check_connection:
            await self.cloud.ensure_not_connected(access_token=cognito.access_token)

        task = await self.cloud.update_token(
            cognito.id_token,
            cognito.access_token,
            cognito.refresh_token,
        )

        if task:
            await task

    async def async_login(
        self,
        email: str,
        password: str,
        *,
        check_connection: bool = False,
    ) -> None:
        """Log user in and fetch certificate."""
        try:
            async with self._request_lock:
                assert not self.cloud.is_logged_in, "Cannot login if already logged in."

                cognito: CognitoAuthClient = await self.cloud.run_executor(
                    partial(self._create_cognito_client, username=email),
                )

                async with async_timeout.timeout(30):
                    await self.cloud.run_executor(
                        partial(cognito.authenticate, password=password),
                    )

                await self._handle_successful_authentication(cognito, check_connection)

        except MFAChallengeError as err:
            raise MFARequired(err.get_tokens()) from err

        except ForceChangePasswordError as err:
            raise PasswordChangeRequired from err

        except ClientError as err:
            raise _map_aws_exception(err) from err

        except BotoCoreError as err:
            raise UnknownError from err

    async def async_login_verify_totp(
        self,
        email: str,
        code: str,
        mfa_tokens: dict[str, Any],
        *,
        check_connection: bool = False,
    ) -> None:
        """Log user in and fetch certificate if MFA is required."""
        try:
            async with self._request_lock:
                assert not self.cloud.is_logged_in, (
                    "Cannot verify TOTP if already logged in."
                )

                cognito: CognitoAuthClient = await self.cloud.run_executor(
                    partial(self._create_cognito_client, username=email),
                )

                async with async_timeout.timeout(30):
                    await self.cloud.run_executor(
                        partial(
                            cognito.respond_to_software_token_mfa_challenge,
                            code=code,
                            mfa_tokens=mfa_tokens,
                        ),
                    )

                if TYPE_CHECKING:
                    assert cognito.access_token is not None, (
                        "Access token should be available after MFA verification"
                    )
                    assert cognito.id_token is not None, (
                        "ID token should be available after MFA verification"
                    )

                await self._handle_successful_authentication(cognito, check_connection)

        except ClientError as err:
            raise _map_aws_exception(err) from err

        except BotoCoreError as err:
            raise UnknownError from err

    async def async_check_token(self) -> None:
        """Check that the token is valid and renew if necessary."""
        async with self._request_lock:
            cognito = await self._async_authenticated_cognito()

            # Check if token is valid
            is_valid = await self.cloud.run_executor(
                partial(cognito.validate_and_renew_token, renew=False)
            )

            if is_valid:
                return

            # Token needs renewal
            try:
                was_renewed = await self.cloud.run_executor(
                    partial(cognito.validate_and_renew_token, renew=True)
                )

                # If token was renewed, update cloud with new tokens
                if was_renewed:
                    assert cognito.access_token is not None
                    assert cognito.id_token is not None
                    await self.cloud.update_token(
                        cognito.id_token, cognito.access_token
                    )

            except ClientError as err:
                mapped_err = _map_aws_exception(err)
                if isinstance(mapped_err, (Unauthenticated, UserNotFound)):
                    _LOGGER.error("Unable to refresh token: %s", mapped_err)

                    self.cloud.client.user_message(
                        "cloud_subscription_expired",
                        "Home Assistant Cloud",
                        MESSAGE_AUTH_FAIL,
                    )

                    # Don't await it because it could cancel this task
                    asyncio.create_task(self.cloud.logout())

                raise mapped_err from err
            except BotoCoreError as err:
                raise UnknownError from err

    async def async_renew_access_token(self) -> None:
        """Renew access token."""
        async with self._request_lock:
            await self._async_renew_access_token()

    async def _async_renew_access_token(self) -> None:
        """Renew access token internals.

        Does not consume lock.
        """
        cognito = await self._async_authenticated_cognito()

        try:
            await self.cloud.run_executor(cognito.renew_access_token)

            # After successful token renewal, tokens should be available
            assert cognito.access_token is not None, (
                "Access token should be available after renewal"
            )
            assert cognito.id_token is not None, (
                "ID token should be available after renewal"
            )

            await self.cloud.update_token(cognito.id_token, cognito.access_token)

        except ClientError as err:
            raise _map_aws_exception(err) from err

        except BotoCoreError as err:
            raise UnknownError from err

    async def _async_authenticated_cognito(self) -> CognitoAuthClient:
        """Return an authenticated cognito instance."""
        if self.cloud.access_token is None or self.cloud.refresh_token is None:
            raise Unauthenticated("No authentication found")

        return cast(
            "CognitoAuthClient",
            await self.cloud.run_executor(
                partial(
                    self._create_cognito_client,
                    access_token=self.cloud.access_token,
                    refresh_token=self.cloud.refresh_token,
                ),
            ),
        )

    def _create_cognito_client(self, **kwargs: Any) -> CognitoAuthClient:
        """Create a new cognito client.

        NOTE: This will do I/O
        """
        if self._session is None:
            self._session = boto3.session.Session()

        return _cached_cognito(
            user_pool_id=self.cloud.user_pool_id,
            client_id=self.cloud.cognito_client_id,
            user_pool_region=self.cloud.region,
            botocore_config=botocore.config.Config(signature_version=botocore.UNSIGNED),
            session=self._session,
            **kwargs,
        )


def _map_aws_exception(err: ClientError) -> CloudError:
    """Map AWS exception to our exceptions."""
    error_code = err.response["Error"]["Code"]
    error_message = err.response["Error"]["Message"]

    match error_code:
        case "CodeMismatchException":
            return InvalidTotpCode(error_message)
        case "UserNotFoundException":
            return UserNotFound(error_message)
        case "UserNotConfirmedException":
            return UserNotConfirmed(error_message)
        case "UsernameExistsException":
            return UserExists(error_message)
        case "NotAuthorizedException":
            return Unauthenticated(error_message)
        case "PasswordResetRequiredException":
            return PasswordChangeRequired(error_message)
        case _:
            return UnknownError(error_message)


@lru_cache(maxsize=2)
def _cached_cognito(
    user_pool_id: str,
    client_id: str,
    user_pool_region: str,
    botocore_config: Any,
    session: Any,
    **kwargs: Any,
) -> CognitoAuthClient:
    """Create a cached cognito client.

    NOTE: This will do I/O
    """
    return CognitoAuthClient(
        user_pool_id=user_pool_id,
        client_id=client_id,
        user_pool_region=user_pool_region,
        botocore_config=botocore_config,
        session=session,
        **kwargs,
    )
