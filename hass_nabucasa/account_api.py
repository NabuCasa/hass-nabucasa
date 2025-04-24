"""Manage account API."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from .api import ApiBase, CloudApiError, api_exception_handler


class AccountApiError(CloudApiError):
    """Exception raised when handling account API."""


class AccountServicesDetails(TypedDict):
    """Details of the services."""

    alexa: AccountServiceDetails
    google_home: AccountServiceDetails
    remote_access: AccountServiceDetails
    stt: AccountServiceDetails
    storage: AccountStorageServiceDetails
    tts: AccountServiceDetails
    webhooks: AccountServiceDetails
    webrtc: AccountServiceDetails


class AccountServiceDetails(TypedDict):
    """Details of a service."""

    available: bool


class AccountStorageServiceDetails(AccountServiceDetails):
    """Details of a service."""

    limit_bytes: int


class AccountApi(ApiBase):
    """Class to help communicate with the instance API."""

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        if TYPE_CHECKING:
            assert self._cloud.servicehandlers_server is not None
        return self._cloud.servicehandlers_server

    @api_exception_handler(AccountApiError)
    async def services(self) -> AccountServicesDetails:
        """Get the services details."""
        details: AccountServicesDetails = await self._call_cloud_api(
            path="/account/services",
        )
        return details
