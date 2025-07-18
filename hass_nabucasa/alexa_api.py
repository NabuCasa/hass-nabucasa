"""This module provides Alexa API functionalities."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

from .api import ApiBase, CloudApiError, CloudApiRawResponse, api_exception_handler

_ALEXA_RELINK_REASONS = frozenset({"RefreshTokenNotFound", "UnknownRegion"})


class AlexaApiError(CloudApiError):
    """Exception raised when handling Alexa API."""


class AlexaApiNeedsRelinkError(AlexaApiError):
    """Exception raised when Alexa API needs to be re-linked."""


class AlexaApiNoTokenError(AlexaApiError):
    """Exception raised when Alexa API access token is not available."""


class AlexaAccessTokenDetails(TypedDict):
    """Alexa access token details from Alexa API."""

    access_token: str
    expires_in: int
    event_endpoint: str


class AlexaAccessTokenError(TypedDict):
    """Alexa access token error details from Alexa API."""

    reason: str


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
        details: CloudApiRawResponse = await self._call_cloud_api(
            method="POST",
            path="/alexa/access_token",
            raw_response=True,
        )

        if details.response.status == 400:
            if (
                isinstance(details.data, dict)
                and (reason := details.data.get("reason"))
                and reason in _ALEXA_RELINK_REASONS
            ):
                raise AlexaApiNeedsRelinkError(
                    reason,
                    reason=reason,
                    status=details.response.status,
                ) from None

            raise AlexaApiNoTokenError(
                "No access token available",
                status=details.response.status,
            ) from None

        if details.response.status >= 400:
            raise CloudApiError(
                f"Failed to fetch: ({details.response.status}) ",
                status=details.response.status,
                reason=(
                    details.data.get("reason")
                    if isinstance(details.data, dict)
                    else None
                ),
            )

        return cast("AlexaAccessTokenDetails", details.data)
