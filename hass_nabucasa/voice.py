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
    ("af-ZA", Gender.FEMALE): "AdriNeural",
    ("af-ZA", Gender.MALE): "WillemNeural",
    ("am-ET", Gender.FEMALE): "MekdesNeural",
    ("am-ET", Gender.MALE): "AmehaNeural",
    ("ar-DZ", Gender.FEMALE): "AminaNeural",
    ("ar-DZ", Gender.MALE): "IsmaelNeural",
    ("ar-BH", Gender.FEMALE): "LailaNeural",
    ("ar-BH", Gender.MALE): "AliNeural",
    ("ar-EG", Gender.FEMALE): "SalmaNeural",
    ("ar-EG", Gender.MALE): "ShakirNeural",
    ("ar-IQ", Gender.FEMALE): "RanaNeural",
    ("ar-IQ", Gender.MALE): "BasselNeural",
    ("ar-JO", Gender.FEMALE): "SanaNeural",
    ("ar-JO", Gender.MALE): "TaimNeural",
    ("ar-KW", Gender.FEMALE): "NouraNeural",
    ("ar-KW", Gender.MALE): "FahedNeural",
    ("ar-LY", Gender.FEMALE): "ImanNeural",
    ("ar-LY", Gender.MALE): "OmarNeural",
    ("ar-MA", Gender.FEMALE): "MounaNeural",
    ("ar-MA", Gender.MALE): "JamalNeural",
    ("ar-QA", Gender.FEMALE): "AmalNeural",
    ("ar-QA", Gender.MALE): "MoazNeural",
    ("ar-SA", Gender.FEMALE): "ZariyahNeural",
    ("ar-SA", Gender.MALE): "HamedNeural",
    ("ar-SY", Gender.FEMALE): "AmanyNeural",
    ("ar-SY", Gender.MALE): "LaithNeural",
    ("ar-TN", Gender.FEMALE): "ReemNeural",
    ("ar-TN", Gender.MALE): "HediNeural",
    ("ar-AE", Gender.FEMALE): "FatimaNeural",
    ("ar-AE", Gender.MALE): "HamdanNeural",
    ("ar-YE", Gender.FEMALE): "MaryamNeural",
    ("ar-YE", Gender.MALE): "SalehNeural",
    ("bn-BD", Gender.FEMALE): "NabanitaNeural",
    ("bn-BD", Gender.MALE): "PradeepNeural",
    ("bn-IN", Gender.FEMALE): "TanishaaNeural",
    ("bn-IN", Gender.MALE): "BashkarNeural",
    ("bg-BG", Gender.FEMALE): "KalinaNeural",
    ("bg-BG", Gender.MALE): "BorislavNeural",
    ("my-MM", Gender.FEMALE): "NilarNeural",
    ("my-MM", Gender.MALE): "ThihaNeural",
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
    ("nl-BE", Gender.FEMALE): "DenaNeural",
    ("nl-BE", Gender.MALE): "ArnaudNeural",
    ("nl-NL", Gender.FEMALE): "ColetteNeural",
    ("nl-NL", Gender.MALE): "MaartenNeural",
    ("en-AU", Gender.FEMALE): "NatashaNeural",
    ("en-AU", Gender.MALE): "WilliamNeural",
    ("en-CA", Gender.FEMALE): "ClaraNeural",
    ("en-CA", Gender.MALE): "LiamNeural",
    ("en-HK", Gender.FEMALE): "YanNeural",
    ("en-HK", Gender.MALE): "SamNeural",
    ("en-IN", Gender.FEMALE): "NeerjaNeural",
    ("en-IN", Gender.MALE): "PrabhatNeural",
    ("en-IE", Gender.FEMALE): "EmilyNeural",
    ("en-IE", Gender.MALE): "ConnorNeural",
    ("en-KE", Gender.FEMALE): "AsiliaNeural",
    ("en-KE", Gender.MALE): "ChilembaNeural",
    ("en-NZ", Gender.FEMALE): "MollyNeural",
    ("en-NZ", Gender.MALE): "MitchellNeural",
    ("en-NG", Gender.FEMALE): "EzinneNeural",
    ("en-NG", Gender.MALE): "AbeoNeural",
    ("en-PH", Gender.FEMALE): "RosaNeural",
    ("en-PH", Gender.MALE): "JamesNeural",
    ("en-SG", Gender.FEMALE): "LunaNeural",
    ("en-SG", Gender.MALE): "WayneNeural",
    ("en-ZA", Gender.FEMALE): "LeahNeural",
    ("en-ZA", Gender.MALE): "LukeNeural",
    ("en-TZ", Gender.FEMALE): "ImaniNeural",
    ("en-TZ", Gender.MALE): "ElimuNeural",
    ("en-GB", Gender.FEMALE): "LibbyNeural",
    ("en-GB", Gender.MALE): "RyanNeural",
    ("en-US", Gender.FEMALE): "JennyNeural",
    ("en-US", Gender.MALE): "GuyNeural",
    ("et-EE", Gender.FEMALE): "AnuNeural",
    ("et-EE", Gender.MALE): "KertNeural",
    ("fil-PH", Gender.FEMALE): "BlessicaNeural",
    ("fil-PH", Gender.MALE): "AngeloNeural",
    ("fi-FI", Gender.FEMALE): "SelmaNeural",
    ("fi-FI", Gender.MALE): "HarriNeural",
    ("fr-BE", Gender.FEMALE): "CharlineNeural",
    ("fr-BE", Gender.MALE): "GerardNeural",
    ("fr-CA", Gender.FEMALE): "SylvieNeural",
    ("fr-CA", Gender.MALE): "AntoineNeural",
    ("fr-FR", Gender.FEMALE): "DeniseNeural",
    ("fr-FR", Gender.MALE): "HenriNeural",
    ("fr-CH", Gender.FEMALE): "ArianeNeural",
    ("fr-CH", Gender.MALE): "FabriceNeural",
    ("gl-ES", Gender.FEMALE): "SabelaNeural",
    ("gl-ES", Gender.MALE): "RoiNeural",
    ("de-AT", Gender.FEMALE): "IngridNeural",
    ("de-AT", Gender.MALE): "JonasNeural",
    ("de-DE", Gender.FEMALE): "KatjaNeural",
    ("de-DE", Gender.MALE): "ConradNeural",
    ("de-CH", Gender.FEMALE): "LeniNeural",
    ("de-CH", Gender.MALE): "JanNeural",
    ("el-GR", Gender.FEMALE): "AthinaNeural",
    ("el-GR", Gender.MALE): "NestorasNeural",
    ("gu-IN", Gender.FEMALE): "DhwaniNeural",
    ("gu-IN", Gender.MALE): "NiranjanNeural",
    ("he-IL", Gender.FEMALE): "HilaNeural",
    ("he-IL", Gender.MALE): "AvriNeural",
    ("hi-IN", Gender.FEMALE): "SwaraNeural",
    ("hi-IN", Gender.MALE): "MadhurNeural",
    ("hu-HU", Gender.FEMALE): "NoemiNeural",
    ("hu-HU", Gender.MALE): "TamasNeural",
    ("is-IS", Gender.FEMALE): "GudrunNeural",
    ("is-IS", Gender.MALE): "GunnarNeural",
    ("id-ID", Gender.FEMALE): "GadisNeural",
    ("id-ID", Gender.MALE): "ArdiNeural",
    ("ga-IE", Gender.FEMALE): "OrlaNeural",
    ("ga-IE", Gender.MALE): "ColmNeural",
    ("it-IT", Gender.FEMALE): "ElsaNeural",
    ("it-IT", Gender.MALE): "DiegoNeural",
    ("ja-JP", Gender.FEMALE): "NanamiNeural",
    ("ja-JP", Gender.MALE): "KeitaNeural",
    ("jv-ID", Gender.FEMALE): "SitiNeural",
    ("jv-ID", Gender.MALE): "DimasNeural",
    ("kn-IN", Gender.FEMALE): "SapnaNeural",
    ("kn-IN", Gender.MALE): "GaganNeural",
    ("kk-KZ", Gender.FEMALE): "AigulNeural",
    ("kk-KZ", Gender.MALE): "DauletNeural",
    ("km-KH", Gender.FEMALE): "SreymomNeural",
    ("km-KH", Gender.MALE): "PisethNeural",
    ("ko-KR", Gender.FEMALE): "SunHiNeural",
    ("ko-KR", Gender.MALE): "InJoonNeural",
    ("lo-LA", Gender.FEMALE): "KeomanyNeural",
    ("lo-LA", Gender.MALE): "ChanthavongNeural",
    ("lv-LV", Gender.FEMALE): "EveritaNeural",
    ("lv-LV", Gender.MALE): "NilsNeural",
    ("lt-LT", Gender.FEMALE): "OnaNeural",
    ("lt-LT", Gender.MALE): "LeonasNeural",
    ("mk-MK", Gender.FEMALE): "MarijaNeural",
    ("mk-MK", Gender.MALE): "AleksandarNeural",
    ("ms-MY", Gender.FEMALE): "YasminNeural",
    ("ms-MY", Gender.MALE): "OsmanNeural",
    ("ml-IN", Gender.FEMALE): "SobhanaNeural",
    ("ml-IN", Gender.MALE): "MidhunNeural",
    ("mt-MT", Gender.FEMALE): "GraceNeural",
    ("mt-MT", Gender.MALE): "JosephNeural",
    ("mr-IN", Gender.FEMALE): "AarohiNeural",
    ("mr-IN", Gender.MALE): "ManoharNeural",
    ("nb-NO", Gender.FEMALE): "IselinNeural",
    ("nb-NO", Gender.MALE): "FinnNeural",
    ("ps-AF", Gender.FEMALE): "LatifaNeural",
    ("ps-AF", Gender.MALE): "GulNawazNeural",
    ("fa-IR", Gender.FEMALE): "DilaraNeural",
    ("fa-IR", Gender.MALE): "FaridNeural",
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
    ("sr-RS", Gender.FEMALE): "SophieNeural",
    ("sr-RS", Gender.MALE): "NicholasNeural",
    ("si-LK", Gender.FEMALE): "ThiliniNeural",
    ("si-LK", Gender.MALE): "SameeraNeural",
    ("sk-SK", Gender.FEMALE): "ViktoriaNeural",
    ("sk-SK", Gender.MALE): "LukasNeural",
    ("sl-SI", Gender.FEMALE): "PetraNeural",
    ("sl-SI", Gender.MALE): "RokNeural",
    ("so-SO", Gender.FEMALE): "UbaxNeural",
    ("so-SO", Gender.MALE): "MuuseNeural",
    ("es-AR", Gender.FEMALE): "ElenaNeural",
    ("es-AR", Gender.MALE): "TomasNeural",
    ("es-BO", Gender.FEMALE): "SofiaNeural",
    ("es-BO", Gender.MALE): "MarceloNeural",
    ("es-CL", Gender.FEMALE): "CatalinaNeural",
    ("es-CL", Gender.MALE): "LorenzoNeural",
    ("es-CO", Gender.FEMALE): "SalomeNeural",
    ("es-CO", Gender.MALE): "GonzaloNeural",
    ("es-CR", Gender.FEMALE): "MariaNeural",
    ("es-CR", Gender.MALE): "JuanNeural",
    ("es-CU", Gender.FEMALE): "BelkysNeural",
    ("es-CU", Gender.MALE): "ManuelNeural",
    ("es-DO", Gender.FEMALE): "RamonaNeural",
    ("es-DO", Gender.MALE): "EmilioNeural",
    ("es-EC", Gender.FEMALE): "AndreaNeural",
    ("es-EC", Gender.MALE): "LuisNeural",
    ("es-SV", Gender.FEMALE): "LorenaNeural",
    ("es-SV", Gender.MALE): "RodrigoNeural",
    ("es-GQ", Gender.FEMALE): "TeresaNeural",
    ("es-GQ", Gender.MALE): "JavierNeural",
    ("es-GT", Gender.FEMALE): "MartaNeural",
    ("es-GT", Gender.MALE): "AndresNeural",
    ("es-HN", Gender.FEMALE): "KarlaNeural",
    ("es-HN", Gender.MALE): "CarlosNeural",
    ("es-MX", Gender.FEMALE): "DaliaNeural",
    ("es-MX", Gender.MALE): "JorgeNeural",
    ("es-NI", Gender.FEMALE): "YolandaNeural",
    ("es-NI", Gender.MALE): "FedericoNeural",
    ("es-PA", Gender.FEMALE): "MargaritaNeural",
    ("es-PA", Gender.MALE): "RobertoNeural",
    ("es-PY", Gender.FEMALE): "TaniaNeural",
    ("es-PY", Gender.MALE): "MarioNeural",
    ("es-PE", Gender.FEMALE): "CamilaNeural",
    ("es-PE", Gender.MALE): "AlexNeural",
    ("es-PR", Gender.FEMALE): "KarinaNeural",
    ("es-PR", Gender.MALE): "VictorNeural",
    ("es-ES", Gender.FEMALE): "ElviraNeural",
    ("es-ES", Gender.MALE): "AlvaroNeural",
    ("es-UY", Gender.FEMALE): "ValentinaNeural",
    ("es-UY", Gender.MALE): "MateoNeural",
    ("es-US", Gender.FEMALE): "PalomaNeural",
    ("es-US", Gender.MALE): "AlonsoNeural",
    ("es-VE", Gender.FEMALE): "PaolaNeural",
    ("es-VE", Gender.MALE): "SebastianNeural",
    ("su-ID", Gender.FEMALE): "TutiNeural",
    ("su-ID", Gender.MALE): "JajangNeural",
    ("sw-KE", Gender.FEMALE): "ZuriNeural",
    ("sw-KE", Gender.MALE): "RafikiNeural",
    ("sw-TZ", Gender.FEMALE): "RehemaNeural",
    ("sw-TZ", Gender.MALE): "DaudiNeural",
    ("sv-SE", Gender.FEMALE): "SofieNeural",
    ("sv-SE", Gender.MALE): "MattiasNeural",
    ("ta-IN", Gender.FEMALE): "PallaviNeural",
    ("ta-IN", Gender.MALE): "ValluvarNeural",
    ("ta-SG", Gender.FEMALE): "VenbaNeural",
    ("ta-SG", Gender.MALE): "AnbuNeural",
    ("ta-LK", Gender.FEMALE): "SaranyaNeural",
    ("ta-LK", Gender.MALE): "KumarNeural",
    ("te-IN", Gender.FEMALE): "ShrutiNeural",
    ("te-IN", Gender.MALE): "MohanNeural",
    ("th-TH", Gender.FEMALE): "AcharaNeural",
    ("th-TH", Gender.MALE): "NiwatNeural",
    ("tr-TR", Gender.FEMALE): "EmelNeural",
    ("tr-TR", Gender.MALE): "AhmetNeural",
    ("uk-UA", Gender.FEMALE): "PolinaNeural",
    ("uk-UA", Gender.MALE): "OstapNeural",
    ("ur-IN", Gender.FEMALE): "GulNeural",
    ("ur-IN", Gender.MALE): "SalmanNeural",
    ("ur-PK", Gender.FEMALE): "UzmaNeural",
    ("ur-PK", Gender.MALE): "AsadNeural",
    ("uz-UZ", Gender.FEMALE): "MadinaNeural",
    ("uz-UZ", Gender.MALE): "SardorNeural",
    ("vi-VN", Gender.FEMALE): "HoaiMyNeural",
    ("vi-VN", Gender.MALE): "NamMinhNeural",
    ("cy-GB", Gender.FEMALE): "NiaNeural",
    ("cy-GB", Gender.MALE): "AledNeural",
    ("zu-ZA", Gender.FEMALE): "ThandoNeural",
    ("zu-ZA", Gender.MALE): "ThembaNeural",
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
