"""Voice handler with Azure."""
from datetime import datetime
from enum import Enum
import logging
from typing import Optional
import xml.etree.ElementTree as ET

import aiohttp
from aiohttp.hdrs import ACCEPT, AUTHORIZATION, CONTENT_TYPE
import attr

from . import cloud_api
from .utils import utc_from_timestamp, utcnow


_LOGGER = logging.getLogger(__name__)


class VoiceError(Exception):
    """General Voice error."""


class VoiceTokenError(VoiceError):
    """Error with token handling."""


class VoiceReturnError(VoiceError):
    """Backend error for voice."""


class Gender(str, Enum):
    """Gender Type for voices."""

    MALE = "male"
    FEMALE = "female"


MAP_VOICE = {
    ("en-US", Gender.MALE): "BenjaminRUS",
    ("en-US", Gender.FEMALE): "ZiraRUS",
    ("de-DE", Gender.MALE): "Stefan, Apollo",
    ("de-DE", Gender.FEMALE): "HeddaRUS",
    ("es-ES", Gender.MALE): "Pablo, Apollo",
    ("es-ES", Gender.FEMALE): "HelenaRUS",
}


@attr.s
class STTResponse:
    """Response of STT."""

    success: bool = attr.ib()
    text: Optional[str] = attr.ib()


class Voice:
    """Class to help manage azure STT and TTS."""

    def __init__(self, cloud):
        """Initialize azure voice."""
        self.cloud = cloud
        self._token: Optional[str] = None
        self._endpoint_tts: Optional[str] = None
        self._endpoint_stt: Optional[str] = None
        self._valid: Optional[datetime] = None

    def _validate_token(self) -> bool:
        """Validate token outside of coroutine."""
        if self._valid and utcnow() < self._valid:
            return True
        return False

    async def _update_token(self) -> None:
        """Update token details."""
        resp = await cloud_api.async_voice_connection_details(self.cloud)
        if resp.status != 200:
            raise VoiceTokenError()

        data = await resp.json()
        self._token = data["authorized_key"]
        self._endpoint_stt = data["endpoint_stt"]
        self._endpoint_tts = data["endpoint_tts"]
        self._valid = utc_from_timestamp(float(data["valid"]))

    async def process_stt(
        self, stream: aiohttp.StreamReader, content: str, language: str
    ) -> STTResponse:
        """Stream Audio to Azure congnitive instance."""
        if not self._validate_token():
            await self._update_token()

        # Send request
        async with self.cloud.websession.post(
            f"{self._endpoint_stt}?language={language}",
            headers={
                CONTENT_TYPE: content,
                AUTHORIZATION: f"Bearer {self._token}",
                ACCEPT: "application/json;text/xml",
            },
            data=stream,
            expect100=True,
            chunked=True,
        ) as resp:
            if resp.status != 200:
                _LOGGER.error("Can't process Speech: %d", resp.status)
                raise VoiceReturnError()
            data = await resp.json()

        # Parse Answer
        return STTResponse(
            data["RecognitionStatus"] == "Success", data.get("DisplayText")
        )

    async def process_tts(self, text, language, gender: Gender) -> bytes:
        """Get Speech from text over Azure."""
        if not self._validate_token():
            await self._update_token()

        # SSML
        xml_body = ET.Element("speak", version="1.0")
        xml_body.set("{http://www.w3.org/XML/1998/namespace}lang", language)
        voice = ET.SubElement(xml_body, "voice")
        voice.set("{http://www.w3.org/XML/1998/namespace}lang", language)
        voice.set(
            "name",
            f"Microsoft Server Speech Text to Speech Voice ({language}, {MAP_VOICE[(language, gender)]})",
        )
        voice.text = text

        # Send request
        async with self.cloud.websession.post(
            self._endpoint_tts,
            headers={
                CONTENT_TYPE: "application/ssml+xml",
                AUTHORIZATION: f"Bearer {self._token}",
                "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
            },
            data=ET.tostring(xml_body),
        ) as resp:
            if resp.status != 200:
                raise VoiceReturnError()
            return await resp.read()
