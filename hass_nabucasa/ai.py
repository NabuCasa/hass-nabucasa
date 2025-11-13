from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from hass_nabucasa.ai_api import AiApiError
from hass_nabucasa.utils import utc_from_timestamp, utcnow

if TYPE_CHECKING:
    from . import Cloud, _ClientT

_LOGGER = logging.getLogger(__name__)


class AiError(Exception):
    """General AI error."""


class AiTokenError(AiError):
    """Error with token handling."""


class Ai:
    """Class to help manage azure STT and TTS."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize azure voice."""
        self.cloud = cloud
        self._token: str | None = None
        self._generate_data_endpoint: str | None = None
        self._generate_image_endpoint: str | None = None
        self._valid_until: datetime | None = None

    def _validate_token(self) -> bool:
        """Validate token outside of coroutine."""
        # Add a 5-minute buffer to avoid race conditions near expiry
        return self.cloud.valid_subscription and bool(
            self._valid_until
            and utcnow() + timedelta(minutes=5) < self._valid_until
        )

    async def _update_token(self) -> None:
        """Update token details."""
        if not self.cloud.valid_subscription:
            raise AiTokenError("Invalid subscription")

        try:
            details = await self.cloud.ai_api.ai_connection_details()
        except AiApiError as err:
            _LOGGER.info("AI token update failed: %s", err)
            raise AiTokenError(err) from err

        _LOGGER.info("AI token updated, valid until %s", details["valid_until"])

        self._token = details["token"]
        self._valid_until = utc_from_timestamp(float(details["valid_until"]))
        self._generate_data_endpoint = details["generate_data_endpoint"]
        self._generate_image_endpoint = details["generate_image_endpoint"]
