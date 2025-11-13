"""This module provides voice API functionalities."""

from __future__ import annotations

from typing import TypedDict

from .api import ApiBase, CloudApiError, api_exception_handler


class AiApiError(CloudApiError):
    """Exception raised when handling AI API."""


class AiConnectionDetails(TypedDict):
    """AI connection details from AI API."""

    token: str
    valid_until: int
    generate_data_endpoint: str
    generate_image_endpoint: str


class AiApi(ApiBase):
    """Class to help communicate with the AI API."""

    @api_exception_handler(AiApiError)
    async def ai_connection_details(self) -> AiConnectionDetails:
        """Get the AI token."""
        token: AiConnectionDetails = await self._call_cloud_api(
            action="ai_connection_details", method="POST"
        )
        return token
