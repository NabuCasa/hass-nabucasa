"""Test for voice functions."""

from datetime import timedelta
import io
import wave

import pytest
import xmltodict

from hass_nabucasa import voice
from hass_nabucasa.auth import Unauthenticated
from hass_nabucasa.voice_api import VoiceApi


@pytest.fixture
def voice_api(auth_cloud_mock):
    """Voice api fixture."""
    auth_cloud_mock.servicehandlers_server = "test.local"
    auth_cloud_mock.voice_api = VoiceApi(auth_cloud_mock)
    return voice.Voice(auth_cloud_mock)


@pytest.fixture(autouse=True)
def mock_voice_connection_details(aioclient_mock):
    """Mock voice connection details."""
    aioclient_mock.get(
        "https://test.local/voice/connection_details",
        json={
            "authorized_key": "test-key",
            "endpoint_stt": "stt-url",
            "endpoint_tts": "tts-url",
            "valid": f"{(voice.utcnow() + timedelta(minutes=9)).timestamp()}",
        },
    )


async def test_token_handling(voice_api, aioclient_mock, mock_voice_connection_details):
    """Test handling around token."""
    assert not voice_api._validate_token()
    await voice_api._update_token()
    assert voice_api._validate_token()

    assert voice_api._endpoint_stt == "stt-url"
    assert voice_api._endpoint_tts == "tts-url"
    assert voice_api._token == "test-key"


async def test_process_stt(voice_api, aioclient_mock, mock_voice_connection_details):
    """Test handling around stt."""
    aioclient_mock.post(
        "stt-url?language=en-US",
        json={"RecognitionStatus": "Success", "DisplayText": "My Text"},
    )
    result = await voice_api.process_stt(
        stream=b"feet",
        content_type="video=test",
        language="en-US",
    )

    assert result.success
    assert result.text == "My Text"


async def test_process_stt_bad_language(voice_api):
    """Test language handling around stt."""
    with pytest.raises(voice.VoiceError, match="Language en-BAD not supported"):
        await voice_api.process_stt(
            stream=b"feet",
            content_type="video=test",
            language="en-BAD",
        )


async def test_process_tts_with_gender(
    voice_api,
    aioclient_mock,
    mock_voice_connection_details,
    snapshot,
):
    """Test handling around tts."""
    aioclient_mock.post(
        "tts-url",
        content=b"My sound",
    )
    result = await voice_api.process_tts(
        text="Text for Saying",
        language="en-US",
        gender=voice.Gender.FEMALE,
        output=voice.AudioOutput.MP3,
    )

    assert result == b"My sound"
    assert aioclient_mock.mock_calls[1][3] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
        "User-Agent": "hass-nabucasa/tests",
    }
    assert xmltodict.parse(aioclient_mock.mock_calls[1][2]) == snapshot


async def test_process_tts_with_voice(
    voice_api,
    aioclient_mock,
    mock_voice_connection_details,
    snapshot,
):
    """Test handling around tts."""
    aioclient_mock.post(
        "tts-url",
        content=b"My sound",
    )
    result = await voice_api.process_tts(
        text="Text for Saying",
        language="nl-NL",
        voice="FennaNeural",
        output=voice.AudioOutput.RAW,
    )

    assert result == b"My sound"
    assert aioclient_mock.mock_calls[1][3] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "raw-16khz-16bit-mono-pcm",
        "User-Agent": "hass-nabucasa/tests",
    }
    assert xmltodict.parse(aioclient_mock.mock_calls[1][2]) == snapshot


async def test_process_tts_stream_with_voice(voice_api, aioclient_mock, snapshot):
    """Test handling around tts streaming."""
    with io.BytesIO() as wav_io:
        wav_writer: wave.Wave_write = wave.open(wav_io, "wb")
        with wav_writer:
            wav_writer.setframerate(24000)
            wav_writer.setsampwidth(2)
            wav_writer.setnchannels(1)
            wav_writer.writeframes(b"My sound")

        wav_io.seek(0)
        wav_bytes = wav_io.getvalue()

    aioclient_mock.post(
        "tts-url",
        content=wav_bytes,
    )

    async def text_gen():
        yield "Text for Say"
        yield "ing. More Text"
        yield " for saying."
        yield "".join(f" Sentence {i}." for i in range(10))

    result = bytearray()
    async for data_chunk in voice_api.process_tts_stream(
        text_stream=text_gen(),
        language="nl-NL",
        voice="FennaNeural",
    ):
        result.extend(data_chunk)

    with io.BytesIO(result) as wav_io:
        wav_reader: wave.Wave_read = wave.open(wav_io, "rb")
        with wav_reader:
            assert wav_reader.getframerate() == 24000
            assert wav_reader.getsampwidth() == 2
            assert wav_reader.getnchannels() == 1
            assert wav_reader.getnframes() == 0  # streaming

        audio_bytes = result[44:]  # skip header

        # 3 audio chunks are produced:
        # 1. First sentence
        # 2. Next 3 sentences.
        # 3. All sentences after that.
        assert audio_bytes == b"My soundMy soundMy sound"

    assert aioclient_mock.mock_calls[1][3] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
        "User-Agent": "hass-nabucasa/tests",
    }
    assert xmltodict.parse(aioclient_mock.mock_calls[1][2]) == snapshot


async def test_process_tts_stream_no_text(voice_api, aioclient_mock):
    """Test tts streaming returns valid WAV header with no text."""
    aioclient_mock.post(
        "tts-url",
        content=b"",
    )

    async def text_gen():
        yield ""

    result = bytearray()
    async for data_chunk in voice_api.process_tts_stream(
        text_stream=text_gen(),
        language="nl-NL",
        voice="FennaNeural",
    ):
        result.extend(data_chunk)

    assert len(result) == 44  # header only

    with io.BytesIO(result) as wav_io:
        wav_reader: wave.Wave_read = wave.open(wav_io, "rb")
        with wav_reader:
            assert wav_reader.getframerate() == 24000
            assert wav_reader.getsampwidth() == 2
            assert wav_reader.getnchannels() == 1
            assert wav_reader.getnframes() == 0  # streaming


async def test_process_tts_with_voice_and_style(
    voice_api,
    aioclient_mock,
    mock_voice_connection_details,
    snapshot,
):
    """Test handling around tts."""
    aioclient_mock.post(
        "tts-url",
        content=b"My sound",
    )

    # Voice with variants
    result = await voice_api.process_tts(
        text="Text for Saying",
        language="de-DE",
        voice="ConradNeural",
        style="cheerful",
        output=voice.AudioOutput.RAW,
    )

    assert result == b"My sound"
    assert aioclient_mock.mock_calls[1][3] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "raw-16khz-16bit-mono-pcm",
        "User-Agent": "hass-nabucasa/tests",
    }
    assert xmltodict.parse(aioclient_mock.mock_calls[1][2]) == snapshot

    with pytest.raises(
        voice.VoiceError,
        match="Unsupported style non-existing-style "
        "for voice ConradNeural in language de-DE",
    ):
        await voice_api.process_tts(
            text="Text for Saying",
            language="de-DE",
            voice="ConradNeural",
            style="non-existing-style",
            output=voice.AudioOutput.RAW,
        )

    # Voice without variants
    result = await voice_api.process_tts(
        text="Text for Saying 2",
        language="en-US",
        voice="MichelleNeural",
        output=voice.AudioOutput.RAW,
    )

    assert result == b"My sound"
    assert aioclient_mock.mock_calls[1][3] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "raw-16khz-16bit-mono-pcm",
        "User-Agent": "hass-nabucasa/tests",
    }
    assert xmltodict.parse(aioclient_mock.mock_calls[2][2]) == snapshot

    with pytest.raises(
        voice.VoiceError,
        match="Unsupported style non-existing-style "
        "for voice MichelleNeural in language en-US",
    ):
        await voice_api.process_tts(
            text="Text for Saying 2",
            language="en-US",
            voice="MichelleNeural",
            style="non-existing-style",
            output=voice.AudioOutput.RAW,
        )


async def test_process_tts_bad_language(voice_api):
    """Test language error handling around tts."""
    with pytest.raises(voice.VoiceError, match="Unsupported language en-BAD"):
        await voice_api.process_tts(
            text="Text for Saying",
            language="en-BAD",
            output=voice.AudioOutput.MP3,
        )


async def test_process_tts_bad_voice(voice_api):
    """Test voice error handling around tts."""
    with pytest.raises(
        voice.VoiceError, match="Unsupported voice Not a US voice for language en-US"
    ):
        await voice_api.process_tts(
            text="Text for Saying",
            language="en-US",
            voice="Not a US voice",
            output=voice.AudioOutput.MP3,
        )


async def test_process_tss_429(
    voice_api,
    mock_voice_connection_details,
    aioclient_mock,
    caplog,
):
    """Test handling of voice with 429."""
    aioclient_mock.post(
        "tts-url",
        status=429,
    )

    with pytest.raises(
        voice.VoiceError, match="Error receiving TTS with en-US/JennyNeural: 429 "
    ):
        await voice_api.process_tts(
            text="Text for Saying",
            language="en-US",
            gender=voice.Gender.FEMALE,
            output=voice.AudioOutput.MP3,
        )

    assert len(aioclient_mock.mock_calls) == 4

    assert "Retrying with new token" in caplog.text


async def test_process_stt_429(
    voice_api,
    mock_voice_connection_details,
    aioclient_mock,
    caplog,
):
    """Test handling of voice with 429."""
    aioclient_mock.post(
        "stt-url",
        status=429,
    )

    with pytest.raises(voice.VoiceError, match="Error processing en-US speech: 429 "):
        await voice_api.process_stt(
            stream=b"feet",
            content_type="video=test",
            language="en-US",
        )

    assert len(aioclient_mock.mock_calls) == 4

    assert "Retrying with new token" in caplog.text


async def test_process_tts_without_authentication(
    voice_api: voice.Voice,
):
    """Test handling of voice without authentication."""

    async def async_check_token(*args, **kwargs):
        """Mock token check."""
        raise Unauthenticated("No authentication")

    voice_api.cloud.auth.async_check_token = async_check_token

    with (
        pytest.raises(
            voice.VoiceError,
            match="No authentication",
        ),
    ):
        await voice_api.process_stt(
            stream=b"feet",
            content_type="video=test",
            language="en-US",
        )
