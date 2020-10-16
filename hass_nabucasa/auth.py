"""Package to communicate with the authentication API."""
import asyncio
from functools import partial
import logging
import random

import boto3
import botocore
from botocore.exceptions import ClientError, EndpointConnectionError
import pycognito
from pycognito.exceptions import ForceChangePasswordException

from .const import MESSAGE_AUTH_FAIL

_LOGGER = logging.getLogger(__name__)


class CloudError(Exception):
    """Base class for cloud related errors."""


class Unauthenticated(CloudError):
    """Raised when authentication failed."""


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
    def __init__(self, message="Password change required."):
        """Initialize a password change required error."""
        super().__init__(message)


class UnknownError(CloudError):
    """Raised when an unknown error occurs."""


AWS_EXCEPTIONS = {
    "UserNotFoundException": UserNotFound,
    "UserNotConfirmedException": UserNotConfirmed,
    "UsernameExistsException": UserExists,
    "NotAuthorizedException": Unauthenticated,
    "PasswordResetRequiredException": PasswordChangeRequired,
}


class CognitoAuth:
    """Handle cloud auth."""

    def __init__(self, cloud):
        """Configure the auth api."""
        self.cloud = cloud
        self._refresh_task = None
        self._session = boto3.session.Session()
        self._request_lock = asyncio.Lock()

        cloud.iot.register_on_connect(self.on_connect)
        cloud.iot.register_on_disconnect(self.on_disconnect)

    async def _async_handle_token_refresh(self):
        """Handle Cloud access token refresh."""
        sleep_time = random.randint(2400, 3600)
        while True:
            try:
                await asyncio.sleep(sleep_time)
                await self.async_renew_access_token()
            except CloudError as err:
                _LOGGER.error("Can't refresh cloud token: %s", err)
            except asyncio.CancelledError:
                # Task is canceled, stop it.
                break

            sleep_time = random.randint(3100, 3600)

    async def on_connect(self):
        """When the instance is connected."""
        self._refresh_task = self.cloud.run_task(self._async_handle_token_refresh())

    async def on_disconnect(self):
        """When the instance is disconnected."""
        self._refresh_task.cancel()

    async def async_register(self, email, password):
        """Register a new account."""
        try:
            async with self._request_lock:
                cognito = self._cognito()
                await self.cloud.run_executor(cognito.register, email, password)

        except ClientError as err:
            raise _map_aws_exception(err) from err
        except EndpointConnectionError as err:
            raise UnknownError() from err

    async def async_resend_email_confirm(self, email):
        """Resend email confirmation."""

        try:
            async with self._request_lock:
                cognito = self._cognito(username=email)
                await self.cloud.run_executor(
                    partial(
                        cognito.client.resend_confirmation_code,
                        Username=email,
                        ClientId=cognito.client_id,
                    )
                )
        except ClientError as err:
            raise _map_aws_exception(err) from err
        except EndpointConnectionError as err:
            raise UnknownError() from err

    async def async_forgot_password(self, email):
        """Initialize forgotten password flow."""

        try:
            async with self._request_lock:
                cognito = self._cognito(username=email)
                await self.cloud.run_executor(cognito.initiate_forgot_password)

        except ClientError as err:
            raise _map_aws_exception(err) from err
        except EndpointConnectionError as err:
            raise UnknownError() from err

    async def async_login(self, email, password):
        """Log user in and fetch certificate."""

        try:
            async with self._request_lock:
                assert not self.cloud.is_logged_in, "Cannot login if already logged in."

                cognito = self._cognito(username=email)
                await self.cloud.run_executor(
                    partial(cognito.authenticate, password=password)
                )
                self.cloud.id_token = cognito.id_token
                self.cloud.access_token = cognito.access_token
                self.cloud.refresh_token = cognito.refresh_token
            await self.cloud.run_executor(self.cloud.write_user_info)

        except ForceChangePasswordException as err:
            raise PasswordChangeRequired() from err

        except ClientError as err:
            raise _map_aws_exception(err) from err

        except EndpointConnectionError as err:
            raise UnknownError() from err

    async def async_check_token(self):
        """Check that the token is valid."""
        async with self._request_lock:
            if not self._authenticated_cognito.check_token(renew=False):
                return

            try:
                await self._async_renew_access_token()
            except Unauthenticated as err:
                _LOGGER.error("Unable to refresh token: %s", err)

                self.cloud.client.user_message(
                    "cloud_subscription_expired",
                    "Home Assistant Cloud",
                    MESSAGE_AUTH_FAIL,
                )

                # Don't await it because it could cancel this task
                self.cloud.run_task(self.cloud.logout())
                raise

    async def async_renew_access_token(self):
        """Renew access token."""
        async with self._request_lock:
            await self._async_renew_access_token()

    async def _async_renew_access_token(self):
        """Renew access token internals.

        Does not consume lock.
        """
        cognito = self._authenticated_cognito

        try:
            await self.cloud.run_executor(cognito.renew_access_token)
            self.cloud.id_token = cognito.id_token
            self.cloud.access_token = cognito.access_token
            await self.cloud.run_executor(self.cloud.write_user_info)

        except ClientError as err:
            raise _map_aws_exception(err) from err

        except EndpointConnectionError as err:
            raise UnknownError() from err

    @property
    def _authenticated_cognito(self):
        """Return an authenticated cognito instance."""
        if self.cloud.access_token is None or self.cloud.refresh_token is None:
            raise Unauthenticated("No authentication found")

        return self._cognito(
            access_token=self.cloud.access_token, refresh_token=self.cloud.refresh_token
        )

    def _cognito(self, **kwargs):
        """Get the client credentials."""
        return pycognito.Cognito(
            user_pool_id=self.cloud.user_pool_id,
            client_id=self.cloud.cognito_client_id,
            user_pool_region=self.cloud.region,
            botocore_config=botocore.config.Config(signature_version=botocore.UNSIGNED),
            session=self._session,
            **kwargs,
        )


def _map_aws_exception(err):
    """Map AWS exception to our exceptions."""
    ex = AWS_EXCEPTIONS.get(err.response["Error"]["Code"], UnknownError)
    return ex(err.response["Error"]["Message"])
