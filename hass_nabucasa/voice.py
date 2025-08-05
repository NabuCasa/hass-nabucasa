"""Voice handler with Azure."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterable
from datetime import datetime
from enum import Enum
import io
import logging
from typing import TYPE_CHECKING
import wave
from xml.etree import ElementTree as ET

from aiohttp.hdrs import ACCEPT, AUTHORIZATION, CONTENT_TYPE, USER_AGENT
import attr
from sentence_stream import SentenceBoundaryDetector

from .utils import utc_from_timestamp, utcnow
from .voice_api import VoiceApiError
from .voice_data import TTS_VOICES

if TYPE_CHECKING:
    from . import Cloud, _ClientT


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


class AudioOutput(str, Enum):
    """Gender Type for voices."""

    MP3 = "mp3"
    RAW = "raw"
    WAV = "wav"


STT_LANGUAGES = [
    "af-ZA",
    "am-ET",
    "ar-AE",
    "ar-BH",
    "ar-DZ",
    "ar-EG",
    "ar-IL",
    "ar-IQ",
    "ar-JO",
    "ar-KW",
    "ar-LB",
    "ar-LY",
    "ar-MA",
    "ar-OM",
    "ar-PS",
    "ar-QA",
    "ar-SA",
    "ar-SY",
    "ar-TN",
    "ar-YE",
    "az-AZ",
    "bg-BG",
    "bn-IN",
    "bs-BA",
    "ca-ES",
    "cs-CZ",
    "cy-GB",
    "da-DK",
    "de-AT",
    "de-CH",
    "de-DE",
    "el-GR",
    "en-AU",
    "en-CA",
    "en-GB",
    "en-GH",
    "en-HK",
    "en-IE",
    "en-IN",
    "en-KE",
    "en-NG",
    "en-NZ",
    "en-PH",
    "en-SG",
    "en-TZ",
    "en-US",
    "en-ZA",
    "es-AR",
    "es-BO",
    "es-CL",
    "es-CO",
    "es-CR",
    "es-CU",
    "es-DO",
    "es-EC",
    "es-ES",
    "es-GQ",
    "es-GT",
    "es-HN",
    "es-MX",
    "es-NI",
    "es-PA",
    "es-PE",
    "es-PR",
    "es-PY",
    "es-SV",
    "es-US",
    "es-UY",
    "es-VE",
    "et-EE",
    "eu-ES",
    "fa-IR",
    "fi-FI",
    "fil-PH",
    "fr-BE",
    "fr-CA",
    "fr-CH",
    "fr-FR",
    "ga-IE",
    "gl-ES",
    "gu-IN",
    "he-IL",
    "hi-IN",
    "hr-HR",
    "hu-HU",
    "hy-AM",
    "id-ID",
    "is-IS",
    "it-CH",
    "it-IT",
    "ja-JP",
    "jv-ID",
    "ka-GE",
    "kk-KZ",
    "km-KH",
    "kn-IN",
    "ko-KR",
    "lo-LA",
    "lt-LT",
    "lv-LV",
    "mk-MK",
    "ml-IN",
    "mn-MN",
    "mr-IN",
    "ms-MY",
    "mt-MT",
    "my-MM",
    "nb-NO",
    "ne-NP",
    "nl-BE",
    "nl-NL",
    "pl-PL",
    "ps-AF",
    "pt-BR",
    "pt-PT",
    "ro-RO",
    "ru-RU",
    "si-LK",
    "sk-SK",
    "sl-SI",
    "so-SO",
    "sq-AL",
    "sr-RS",
    "sv-SE",
    "sw-KE",
    "sw-TZ",
    "ta-IN",
    "te-IN",
    "th-TH",
    "tr-TR",
    "uk-UA",
    "uz-UZ",
    "vi-VN",
    "wuu-CN",
    "yue-CN",
    "zh-CN",
    "zh-CN-shandong",
    "zh-CN-sichuan",
    "zh-HK",
    "zh-TW",
    "zu-ZA",
]

# Old. Do not update anymore.
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
    text: str | None = attr.ib()


class Voice:
    """Class to help manage azure STT and TTS."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize azure voice."""
        self.cloud = cloud
        self._token: str | None = None
        self._endpoint_tts: str | None = None
        self._endpoint_stt: str | None = None
        self._valid: datetime | None = None

    def _validate_token(self) -> bool:
        """Validate token outside of coroutine."""
        return self.cloud.valid_subscription and bool(
            self._valid and utcnow() < self._valid
        )

    async def _update_token(self) -> None:
        """Update token details."""
        if not self.cloud.valid_subscription:
            raise VoiceTokenError("Invalid subscription")

        try:
            details = await self.cloud.voice_api.connection_details()
        except VoiceApiError as err:
            raise VoiceTokenError(err) from err

        self._token = details["authorized_key"]
        self._endpoint_stt = details["endpoint_stt"]
        self._endpoint_tts = details["endpoint_tts"]
        self._valid = utc_from_timestamp(float(details["valid"]))

    async def process_stt(
        self,
        *,
        stream: AsyncIterable[bytes],
        content_type: str,
        language: str,
        force_token_renewal: bool = False,
    ) -> STTResponse:
        """Stream Audio to Azure cognitive instance."""
        if language not in STT_LANGUAGES:
            raise VoiceError(f"Language {language} not supported")

        if force_token_renewal or not self._validate_token():
            await self._update_token()

        # Send request
        async with self.cloud.websession.post(
            f"{self._endpoint_stt}?language={language}&profanity=raw",
            headers={
                CONTENT_TYPE: content_type,
                AUTHORIZATION: f"Bearer {self._token}",
                ACCEPT: "application/json;text/xml",
                USER_AGENT: self.cloud.client.client_name,
            },
            data=stream,
            expect100=True,
            chunked=True,
        ) as resp:
            if resp.status == 429 and not force_token_renewal:
                # By checking the force_token_renewal argument, we limit retries to 1.
                _LOGGER.info("Retrying with new token")
                return await self.process_stt(
                    stream=stream,
                    content_type=content_type,
                    language=language,
                    force_token_renewal=True,
                )
            if resp.status not in (200, 201):
                raise VoiceReturnError(
                    f"Error processing {language} speech: "
                    f"{resp.status} {await resp.text()}",
                )
            data = await resp.json()

        # Parse Answer
        return STTResponse(
            data["RecognitionStatus"] == "Success",
            data.get("DisplayText"),
        )

    async def process_tts(
        self,
        *,
        text: str,
        language: str,
        output: AudioOutput,
        voice: str | None = None,
        gender: Gender | None = None,
        force_token_renewal: bool = False,
        style: str | None = None,
    ) -> bytes:
        """Get Speech from text over Azure."""
        if (language_info := TTS_VOICES.get(language)) is None:
            raise VoiceError(f"Unsupported language {language}")

        # Backwards compatibility for old config
        if voice is None and gender is not None:
            voice = MAP_VOICE.get((language, gender))

        # If no voice picked, pick first one.
        if voice is None:
            voice = next(iter(language_info))

        if (voice_info := language_info.get(voice)) is None:
            raise VoiceError(f"Unsupported voice {voice} for language {language}")

        if style and (
            isinstance(voice_info, str) or style not in voice_info.get("variants", [])
        ):
            raise VoiceError(
                f"Unsupported style {style} for voice {voice} in language {language}"
            )

        if force_token_renewal or not self._validate_token():
            await self._update_token()

        # SSML
        xml_body = ET.Element(
            "speak",
            attrib={
                "version": "1.0",
                "xmlns": "http://www.w3.org/2001/10/synthesis",
                "xmlns:mstts": "https://www.w3.org/2001/mstts",
                "{http://www.w3.org/XML/1998/namespace}lang": language,
            },
        )

        # Add <voice> element
        voice_el = ET.SubElement(
            xml_body, "voice", attrib={"name": f"{language}-{voice}"}
        )

        if style:
            express_el = ET.SubElement(
                voice_el,
                "mstts:express-as",
                attrib={
                    "style": style,
                },
            )

            target_el = express_el
        else:
            target_el = voice_el

        target_el.text = text[:2048]

        # We can not get here without this being set, but mypy does not know that.
        assert self._endpoint_tts is not None

        if output == AudioOutput.RAW:
            output_header = "raw-16khz-16bit-mono-pcm"
        elif output == AudioOutput.WAV:
            output_header = "riff-24khz-16bit-mono-pcm"
        else:
            output_header = "audio-24khz-48kbitrate-mono-mp3"

        # Send request
        async with self.cloud.websession.post(
            self._endpoint_tts,
            headers={
                CONTENT_TYPE: "application/ssml+xml",
                AUTHORIZATION: f"Bearer {self._token}",
                "X-Microsoft-OutputFormat": output_header,
                USER_AGENT: self.cloud.client.client_name,
            },
            data=ET.tostring(xml_body),
        ) as resp:
            if resp.status == 429 and not force_token_renewal:
                # By checking the force_token_renewal argument, we limit retries to 1.
                _LOGGER.info("Retrying with new token")
                return await self.process_tts(
                    text=text,
                    language=language,
                    output=output,
                    voice=voice,
                    gender=gender,
                    force_token_renewal=True,
                )
            if resp.status not in (200, 201):
                raise VoiceReturnError(
                    f"Error receiving TTS with {language}/{voice}: "
                    f"{resp.status} {await resp.text()}",
                )
            return await resp.read()

    async def process_tts_stream(
        self,
        *,
        text_stream: AsyncIterable[str],
        language: str,
        voice: str | None = None,
        gender: Gender | None = None,
        style: str | None = None,
    ) -> AsyncGenerator[bytes]:
        """Get streaming Speech from text over Azure."""
        boundary_detector = SentenceBoundaryDetector()
        sentences: list[str] = []
        sentences_ready = asyncio.Event()
        sentences_complete = False
        wav_header_sent = False

        async def _add_sentences() -> None:
            nonlocal sentences_complete

            try:
                # Text chunks may not be on word or sentence boundaries
                async for text_chunk in text_stream:
                    for sentence in boundary_detector.add_chunk(text_chunk):
                        if not sentence.strip():
                            continue

                        sentences.append(sentence)

                    if not sentences:
                        continue

                    sentences_ready.set()

                # Final sentence
                if text := boundary_detector.finish():
                    sentences.append(text)
            finally:
                sentences_complete = True
                sentences_ready.set()

        _add_sentences_task = asyncio.create_task(_add_sentences())

        # Process new sentences as they're available, but synthesize the first
        # one immediately. While that's playing, synthesize (up to) the next 3
        # sentences. After that, synthesize all completed sentences as they're
        # available.
        sentence_schedule = [1, 3]
        while True:
            await sentences_ready.wait()

            if not sentences_complete:
                # Don't wait again if no more sentences are coming
                sentences_ready.clear()

            if not sentences:
                if sentences_complete:
                    # Exit TTS loop
                    break

                # More sentences may be coming
                continue

            new_sentences = sentences[:]
            sentences.clear()

            while new_sentences:
                if sentence_schedule:
                    max_sentences = sentence_schedule.pop(0)
                    sentences_to_process = new_sentences[:max_sentences]
                    new_sentences = new_sentences[len(sentences_to_process) :]
                else:
                    # Process all available sentences together
                    sentences_to_process = new_sentences[:]
                    new_sentences.clear()

                # Combine all new sentences completed to this point
                text = " ".join(sentences_to_process).strip()

                if not text:
                    continue

                # Synthesize audio while text chunks are still being accumulated
                wav_bytes = await self.process_tts(
                    text=text,
                    language=language,
                    output=AudioOutput.WAV,
                    voice=voice,
                    gender=gender,
                    style=style,
                )
                header_bytes, audio_bytes = _split_wav_header(wav_bytes)
                if not wav_header_sent:
                    # Send WAV header once, then stream audio
                    yield header_bytes
                    wav_header_sent = True

                yield audio_bytes

        if not wav_header_sent:
            # Send empty WAV header if no audio data was received.
            # Without this, downstream audio processing will fail.
            yield _make_wav_header(rate=24000, width=2, channels=1)


def _split_wav_header(wav_bytes: bytes) -> tuple[bytes, bytes]:
    """Split WAV into (header, audio) tuple."""
    with io.BytesIO(wav_bytes) as wav_io:
        wav_reader: wave.Wave_read = wave.open(wav_io, "rb")  # noqa: SIM115
        with wav_reader:
            return (
                _make_wav_header(
                    rate=wav_reader.getframerate(),
                    width=wav_reader.getsampwidth(),
                    channels=wav_reader.getnchannels(),
                ),
                wav_reader.readframes(wav_reader.getnframes()),
            )


def _make_wav_header(rate: int, width: int, channels: int) -> bytes:
    """Return WAV header with nframes = 0 for streaming."""
    with io.BytesIO() as wav_io:
        wav_writer: wave.Wave_write = wave.open(wav_io, "wb")  # noqa: SIM115
        with wav_writer:
            wav_writer.setframerate(rate)
            wav_writer.setsampwidth(width)
            wav_writer.setnchannels(channels)

        wav_io.seek(0)
        return wav_io.getvalue()
