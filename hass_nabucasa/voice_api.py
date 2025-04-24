"""This module provides voice API functionalities."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from .api import ApiBase, CloudApiError, api_exception_handler


class VoiceApiError(CloudApiError):
    """Exception raised when handling voice API."""


class VoiceConnectionDetails(TypedDict):
    """Voice connection details from voice API."""

    authorized_key: str
    endpoint_stt: str
    endpoint_tts: str
    valid: str


class VoiceApi(ApiBase):
    """Class to help communicate with the voice API."""

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        if TYPE_CHECKING:
            assert self._cloud.servicehandlers_server is not None
        return self._cloud.servicehandlers_server

    @api_exception_handler(VoiceApiError)
    async def connection_details(self) -> VoiceConnectionDetails:
        """Get the voice connection details."""
        details: VoiceConnectionDetails = await self._call_cloud_api(
            path="/voice/connection_details"
        )
        return details
