"""This module provides voice API functionalities."""

from __future__ import annotations

from typing import TypedDict

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

    @api_exception_handler(VoiceApiError)
    async def connection_details(self) -> VoiceConnectionDetails:
        """Get the voice connection details."""
        details: VoiceConnectionDetails = await self._call_cloud_api(
            action="voice_connection_details"
        )
        return details
