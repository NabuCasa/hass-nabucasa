from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, TypedDict

from .api import ApiBase, CloudApiError
from hass_nabucasa.utils import utc_from_timestamp, utcnow

if TYPE_CHECKING:
    from . import Cloud, _ClientT

_LOGGER = logging.getLogger(__name__)

class AiError(Exception):
    """Error with token handling."""

class AiConnectionDetails(TypedDict):
    """AI connection details from AI API."""

    token: str
    valid_until: int
    generate_data_endpoint: str
    generate_image_endpoint: str

class Ai(ApiBase):
    """Class to handle AI services."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize AI services."""
        super().__init__(cloud)
        self._token: str | None = None
        self._generate_data_endpoint: str | None = None
        self._generate_image_endpoint: str | None = None
        self._valid_until: datetime | None = None

    def _validate_token(self) -> bool:
        """Validate token outside of coroutine."""
        # Add a 5-minute buffer to avoid race conditions near expiry
        return self._cloud.valid_subscription and bool(
            self._valid_until
            and utcnow() + timedelta(minutes=5) < self._valid_until
        )

    async def _update_token(self) -> None:
        """Update token details."""
        if not self._cloud.valid_subscription:
            raise AiError("Invalid subscription")

        try:
            details: AiConnectionDetails = await self._call_cloud_api(
                action="ai_connection_details",
            )

        except CloudApiError as err:
            _LOGGER.error("Failed to update AI token: %s", err)
            raise AiError(err) from err

        self._token = details["token"]
        self._valid_until = utc_from_timestamp(float(details["valid_until"]))
        self._generate_data_endpoint = details["generate_data_endpoint"]
        self._generate_image_endpoint = details["generate_image_endpoint"]
