"""Package to communicate with the authentication API."""
import asyncio
import logging
import random

import boto3
import botocore
from botocore.exceptions import ClientError, EndpointConnectionError
import warrant
from warrant.exceptions import ForceChangePasswordException

_LOGGER = logging.getLogger(__name__)


class CloudError(Exception):
    """Base class for cloud related errors."""


class Unauthenticated(CloudError):
    """Raised when authentication failed."""


class UserNotFound(CloudError):
    """Raised when a user is not found."""


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
    "NotAuthorizedException": Unauthenticated,
    "UserNotConfirmedException": UserNotConfirmed,
    "PasswordResetRequiredException": PasswordChangeRequired,
}


class CognitoAuth:
    """Handle cloud auth."""

    def __init__(self, cloud):
        """Configure the auth api."""
        self.cloud = cloud
        self._refresh_task = None

        cloud.iot.register_on_connect(self.on_connect)
        cloud.iot.register_on_disconnect(self.on_disconnect)

    async def handle_token_refresh(self):
        """Handle Cloud access token refresh."""
        sleep_time = random.randint(2400, 3600)
        while True:
            try:
                await asyncio.sleep(sleep_time)
                await self.cloud.run_executor(self.renew_access_token)
            except CloudError as err:
                _LOGGER.error("Can't refresh cloud token: %s", err)
            except asyncio.CancelledError:
                # Task is canceled, stop it.
                break

            sleep_time = random.randint(3100, 3600)

    async def on_connect(self):
        """When the instance is connected."""
        self._refresh_task = self.cloud.run_task(self.handle_token_refresh())

    async def on_disconnect(self):
        """When the instance is disconnected."""
        self._refresh_task.cancel()

    def register(self, email, password):
        """Register a new account."""
        cognito = self._cognito()

        # Workaround for bug in Warrant. PR with fix:
        # https://github.com/capless/warrant/pull/82
        cognito.add_base_attributes()
        try:
            cognito.register(email, password)

        except ClientError as err:
            raise _map_aws_exception(err)
        except EndpointConnectionError:
            raise UnknownError()

    def resend_email_confirm(self, email):
        """Resend email confirmation."""
        cognito = self._cognito(username=email)

        try:
            cognito.client.resend_confirmation_code(
                Username=email, ClientId=cognito.client_id
            )
        except ClientError as err:
            raise _map_aws_exception(err)
        except EndpointConnectionError:
            raise UnknownError()

    def forgot_password(self, email):
        """Initialize forgotten password flow."""
        cognito = self._cognito(username=email)

        try:
            cognito.initiate_forgot_password()

        except ClientError as err:
            raise _map_aws_exception(err)
        except EndpointConnectionError:
            raise UnknownError()

    def login(self, email, password):
        """Log user in and fetch certificate."""
        cognito = self._authenticate(email, password)
        self.cloud.id_token = cognito.id_token
        self.cloud.access_token = cognito.access_token
        self.cloud.refresh_token = cognito.refresh_token
        self.cloud.write_user_info()

    def check_token(self):
        """Check that the token is valid and verify if needed."""
        cognito = self._cognito(
            access_token=self.cloud.access_token, refresh_token=self.cloud.refresh_token
        )

        try:
            if cognito.check_token():
                self.cloud.id_token = cognito.id_token
                self.cloud.access_token = cognito.access_token
                self.cloud.write_user_info()

        except ClientError as err:
            raise _map_aws_exception(err)

        except EndpointConnectionError:
            raise UnknownError()

    def renew_access_token(self):
        """Renew access token."""
        cognito = self._cognito(
            access_token=self.cloud.access_token, refresh_token=self.cloud.refresh_token
        )

        try:
            cognito.renew_access_token()
            self.cloud.id_token = cognito.id_token
            self.cloud.access_token = cognito.access_token
            self.cloud.write_user_info()

        except ClientError as err:
            raise _map_aws_exception(err)

        except EndpointConnectionError:
            raise UnknownError()

    def _authenticate(self, email, password):
        """Log in and return an authenticated Cognito instance."""
        assert not self.cloud.is_logged_in, "Cannot login if already logged in."

        cognito = self._cognito(username=email)
        try:
            cognito.authenticate(password=password)
            return cognito

        except ForceChangePasswordException:
            raise PasswordChangeRequired()

        except ClientError as err:
            raise _map_aws_exception(err)

        except EndpointConnectionError:
            raise UnknownError()

    def _cognito(self, **kwargs):
        """Get the client credentials."""
        cognito = warrant.Cognito(
            user_pool_id=self.cloud.user_pool_id,
            client_id=self.cloud.cognito_client_id,
            user_pool_region=self.cloud.region,
            **kwargs
        )
        cognito.client = boto3.client(
            "cognito-idp",
            region_name=self.cloud.region,
            config=botocore.config.Config(signature_version=botocore.UNSIGNED),
        )
        return cognito


def _map_aws_exception(err):
    """Map AWS exception to our exceptions."""
    ex = AWS_EXCEPTIONS.get(err.response["Error"]["Code"], UnknownError)
    return ex(err.response["Error"]["Message"])
