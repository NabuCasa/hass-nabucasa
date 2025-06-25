"""This module provides Alexa API functionalities."""
from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from .api import ApiBase, CloudApiError, api_exception_handler


class AlexaApiError(CloudApiError):
    """Exception raised when handling Alexa API."""


class AlexaAccessTokenDetails(TypedDict):
    """Alexa access token details from Alexa API."""

    access_token: str
    expires_in: int
    event_endpoint: str


class AlexaApi(ApiBase):
    """Class to help communicate with the Alexa API."""

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        if TYPE_CHECKING:
            assert self._cloud.servicehandlers_server is not None
        return self._cloud.servicehandlers_server

    @api_exception_handler(AlexaApiError)
    async def access_token(self) -> AlexaAccessTokenDetails:
        """Get the Alexa API access token."""
        details: AlexaAccessTokenDetails = await self._call_cloud_api(
            method="POST",
            path="/alexa/access_token"
        )
        return details
