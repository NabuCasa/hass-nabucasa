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
    ("ar-EG", Gender.FEMALE): "SalmaNeural",
    ("ar-EG", Gender.MALE): "ShakirNeural",
    ("ar-SA", Gender.FEMALE): "ZariyahNeural",
    ("ar-SA", Gender.MALE): "HamedNeural",
    ("bg-BG", Gender.FEMALE): "KalinaNeural",
    ("bg-BG", Gender.MALE): "BorislavNeural",
    ("ca-ES", Gender.FEMALE): "JoanaNeural",
    ("ca-ES", Gender.MALE): "EnricNeural",
    ("zh-HK", Gender.FEMALE): "HiuMaanNeural",
    ("zh-HK", Gender.MALE): "WanLungNeural",
    ("zh-CN", Gender.FEMALE): "XiaoxiaoNeural",
    ("zh-CN", Gender.MALE): "YunyangNeural",
    ("zh-TW", Gender.FEMALE): "HsiaoChenNeural",
    ("zh-TW", Gender.MALE): "YunJheNeural",
    ("hr-HR", Gender.FEMALE): "GabrijelaNeural",
    ("hr-HR", Gender.MALE): "SreckoNeural",
    ("cs-CZ", Gender.FEMALE): "VlastaNeural",
    ("cs-CZ", Gender.MALE): "AntoninNeural",
    ("da-DK", Gender.FEMALE): "ChristelNeural",
    ("da-DK", Gender.MALE): "JeppeNeural",
    ("nl-NL", Gender.FEMALE): "ColetteNeural",
    ("nl-NL", Gender.MALE): "MaartenNeural",
    ("en-AU", Gender.FEMALE): "NatashaNeural",
    ("en-AU", Gender.MALE): "WilliamNeural",
    ("en-CA", Gender.FEMALE): "ClaraNeural",
    ("en-CA", Gender.MALE): "LiamNeural",
    ("en-IN", Gender.FEMALE): "NeerjaNeural",
    ("en-IN", Gender.MALE): "PrabhatNeural",
    ("en-IE", Gender.FEMALE): "EmilyNeural",
    ("en-IE", Gender.MALE): "ConnorNeural",
    ("en-GB", Gender.FEMALE): "MiaNeural",
    ("en-GB", Gender.MALE): "RyanNeural",
    ("en-US", Gender.FEMALE): "JennyNeural",
    ("en-US", Gender.MALE): "GuyNeural",
    ("fi-FI", Gender.FEMALE): "SelmaNeural",
    ("fi-FI", Gender.MALE): "HarriNeural",
    ("fr-CA", Gender.FEMALE): "SylvieNeural",
    ("fr-CA", Gender.MALE): "AntoineNeural",
    ("fr-FR", Gender.FEMALE): "DeniseNeural",
    ("fr-FR", Gender.MALE): "HenriNeural",
    ("fr-CH", Gender.FEMALE): "ArianeNeural",
    ("fr-CH", Gender.MALE): "FabriceNeural",
    ("de-AT", Gender.FEMALE): "IngridNeural",
    ("de-AT", Gender.MALE): "JonasNeural",
    ("de-DE", Gender.FEMALE): "KatjaNeural",
    ("de-DE", Gender.MALE): "ConradNeural",
    ("de-CH", Gender.FEMALE): "LeniNeural",
    ("de-CH", Gender.MALE): "JanNeural",
    ("el-GR", Gender.FEMALE): "AthinaNeural",
    ("el-GR", Gender.MALE): "NestorasNeural",
    ("he-IL", Gender.FEMALE): "HilaNeural",
    ("he-IL", Gender.MALE): "AvriNeural",
    ("hi-IN", Gender.FEMALE): "SwaraNeural",
    ("hi-IN", Gender.MALE): "MadhurNeural",
    ("hu-HU", Gender.FEMALE): "NoemiNeural",
    ("hu-HU", Gender.MALE): "TamasNeural",
    ("id-ID", Gender.FEMALE): "GadisNeural",
    ("id-ID", Gender.MALE): "ArdiNeural",
    ("it-IT", Gender.FEMALE): "ElsaNeural",
    ("it-IT", Gender.MALE): "DiegoNeural",
    ("ja-JP", Gender.FEMALE): "NanamiNeural",
    ("ja-JP", Gender.MALE): "KeitaNeural",
    ("ko-KR", Gender.FEMALE): "SunHiNeural",
    ("ko-KR", Gender.MALE): "InJoonNeural",
    ("ms-MY", Gender.FEMALE): "YasminNeural",
    ("ms-MY", Gender.MALE): "OsmanNeural",
    ("nb-NO", Gender.FEMALE): "IselinNeural",
    ("nb-NO", Gender.MALE): "FinnNeural",
    ("pl-PL", Gender.FEMALE): "AgnieszkaNeural",
    ("pl-PL", Gender.MALE): "MarekNeural",
    ("pt-BR", Gender.FEMALE): "FranciscaNeural",
    ("pt-BR", Gender.MALE): "AntonioNeural",
    ("pt-PT", Gender.FEMALE): "RaquelNeural",
    ("pt-PT", Gender.MALE): "DuarteNeural",
    ("ro-RO", Gender.FEMALE): "AlinaNeural",
    ("ro-RO", Gender.MALE): "EmilNeural",
    ("ru-RU", Gender.FEMALE): "SvetlanaNeural",
    ("ru-RU", Gender.MALE): "DmitryNeural",
    ("sk-SK", Gender.FEMALE): "ViktoriaNeural",
    ("sk-SK", Gender.MALE): "LukasNeural",
    ("sl-SI", Gender.FEMALE): "PetraNeural",
    ("sl-SI", Gender.MALE): "RokNeural",
    ("es-MX", Gender.FEMALE): "DaliaNeural",
    ("es-MX", Gender.MALE): "JorgeNeural",
    ("es-ES", Gender.FEMALE): "ElviraNeural",
    ("es-ES", Gender.MALE): "AlvaroNeural",
    ("sv-SE", Gender.FEMALE): "SofieNeural",
    ("sv-SE", Gender.MALE): "MattiasNeural",
    ("ta-IN", Gender.FEMALE): "PallaviNeural",
    ("ta-IN", Gender.MALE): "ValluvarNeural",
    ("te-IN", Gender.FEMALE): "ShrutiNeural",
    ("te-IN", Gender.MALE): "MohanNeural",
    ("th-TH", Gender.FEMALE): "AcharaNeural",
    ("th-TH", Gender.MALE): "NiwatNeural",
    ("tr-TR", Gender.FEMALE): "EmelNeural",
    ("tr-TR", Gender.MALE): "AhmetNeural",
    ("vi-VN", Gender.FEMALE): "HoaiMyNeural",
    ("vi-VN", Gender.MALE): "NamMinhNeural",
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

    async def process_tts(self, text: str, language: str, gender: Gender) -> bytes:
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
        voice.text = text[:2048]

        # Send request
        async with self.cloud.websession.post(
            self._endpoint_tts,
            headers={
                CONTENT_TYPE: "application/ssml+xml",
                AUTHORIZATION: f"Bearer {self._token}",
                "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            },
            data=ET.tostring(xml_body),
        ) as resp:
            if resp.status != 200:
                raise VoiceReturnError()
            return await resp.read()
