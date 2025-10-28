"""Test for voice functions."""

import asyncio
from datetime import timedelta
import io
from unittest.mock import patch
import wave

import pytest
import xmltodict

from hass_nabucasa import Cloud, voice
from hass_nabucasa.auth import Unauthenticated


@pytest.fixture(autouse=True)
def mock_voice_connection_details(aioclient_mock):
    """Mock voice connection details."""
    aioclient_mock.get(
        "https://servicehandlers.example.com/voice/connection_details",
        json={
            "authorized_key": "test-key",
            "endpoint_stt": "stt-url",
            "endpoint_tts": "tts-url",
            "valid": f"{(voice.utcnow() + timedelta(minutes=9)).timestamp()}",
        },
    )


async def test_token_handling(
    cloud: Cloud, aioclient_mock, mock_voice_connection_details
):
    """Test handling around token."""
    assert not cloud.voice._validate_token()
    await cloud.voice._update_token()
    assert cloud.voice._validate_token()

    assert cloud.voice._endpoint_stt == "stt-url"
    assert cloud.voice._endpoint_tts == "tts-url"
    assert cloud.voice._token == "test-key"


async def test_process_stt(cloud: Cloud, aioclient_mock, mock_voice_connection_details):
    """Test handling around stt."""
    aioclient_mock.post(
        "stt-url?language=en-US",
        json={"RecognitionStatus": "Success", "DisplayText": "My Text"},
    )
    result = await cloud.voice.process_stt(
        stream=b"feet",
        content_type="video=test",
        language="en-US",
    )

    assert result.success
    assert result.text == "My Text"


async def test_process_stt_bad_language(cloud: Cloud):
    """Test language handling around stt."""
    with pytest.raises(voice.VoiceError, match="Language en-BAD not supported"):
        await cloud.voice.process_stt(
            stream=b"feet",
            content_type="video=test",
            language="en-BAD",
        )


async def test_process_tts_with_gender(
    cloud: Cloud,
    aioclient_mock,
    mock_voice_connection_details,
    snapshot,
):
    """Test handling around tts."""
    aioclient_mock.post(
        "tts-url",
        content=b"My sound",
    )
    result = await cloud.voice.process_tts(
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
    cloud: Cloud,
    aioclient_mock,
    mock_voice_connection_details,
    snapshot,
):
    """Test handling around tts."""
    aioclient_mock.post(
        "tts-url",
        content=b"My sound",
    )
    result = await cloud.voice.process_tts(
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


async def test_process_tts_stream_with_voice(cloud: Cloud, aioclient_mock, snapshot):
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
    async for data_chunk in cloud.voice.process_tts_stream(
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


async def test_process_tts_stream_with_voice_final_sentence(
    cloud: Cloud, aioclient_mock, snapshot
):
    """Test handling around tts streaming with final sentence."""
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

    # Use events to force the following order of events:
    # 1. text chunk is emitted with enough for 1 sentence
    # 2. TTS starts
    # 3. final text chunk is emitted *before* TTS finishes
    # 4. final sentence TTS is processed in the next loop
    #
    # We must check that the final sentence is not dropped because the previous
    # TTS is on-going.
    chunk_event = asyncio.Event()
    tts_event = asyncio.Event()
    first_chunk = True

    async def process_tts(*args, **kwargs):
        nonlocal first_chunk

        if first_chunk:
            first_chunk = False
            await chunk_event.wait()
            chunk_event.clear()
            tts_event.set()
            await chunk_event.wait()

        return wav_bytes

    async def text_gen():
        yield "Test 1. \n\nTest"
        chunk_event.set()

        yield " 2."
        await tts_event.wait()
        chunk_event.set()

    result = bytearray()
    with patch.object(cloud.voice, "process_tts", process_tts):
        async for data_chunk in cloud.voice.process_tts_stream(
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

            assert audio_bytes == b"My soundMy sound"


async def test_process_tts_stream_no_text(cloud: Cloud, aioclient_mock):
    """Test tts streaming returns valid WAV header with no text."""
    aioclient_mock.post(
        "tts-url",
        content=b"",
    )

    async def text_gen():
        yield ""

    result = bytearray()
    async for data_chunk in cloud.voice.process_tts_stream(
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
    cloud: Cloud,
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
    result = await cloud.voice.process_tts(
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
        await cloud.voice.process_tts(
            text="Text for Saying",
            language="de-DE",
            voice="ConradNeural",
            style="non-existing-style",
            output=voice.AudioOutput.RAW,
        )

    # Voice without variants
    result = await cloud.voice.process_tts(
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
        await cloud.voice.process_tts(
            text="Text for Saying 2",
            language="en-US",
            voice="MichelleNeural",
            style="non-existing-style",
            output=voice.AudioOutput.RAW,
        )


async def test_process_tts_bad_language(cloud: Cloud):
    """Test language error handling around tts."""
    with pytest.raises(voice.VoiceError, match="Unsupported language en-BAD"):
        await cloud.voice.process_tts(
            text="Text for Saying",
            language="en-BAD",
            output=voice.AudioOutput.MP3,
        )


async def test_process_tts_bad_voice(cloud: Cloud):
    """Test voice error handling around tts."""
    with pytest.raises(
        voice.VoiceError, match="Unsupported voice Not a US voice for language en-US"
    ):
        await cloud.voice.process_tts(
            text="Text for Saying",
            language="en-US",
            voice="Not a US voice",
            output=voice.AudioOutput.MP3,
        )


async def test_process_tss_429(
    cloud: Cloud,
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
        await cloud.voice.process_tts(
            text="Text for Saying",
            language="en-US",
            gender=voice.Gender.FEMALE,
            output=voice.AudioOutput.MP3,
        )

    assert len(aioclient_mock.mock_calls) == 4

    assert "Retrying with new token" in caplog.text


async def test_process_stt_429(
    cloud: Cloud,
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
        await cloud.voice.process_stt(
            stream=b"feet",
            content_type="video=test",
            language="en-US",
        )

    assert len(aioclient_mock.mock_calls) == 4

    assert "Retrying with new token" in caplog.text


async def test_process_tts_without_authentication(
    cloud: Cloud,
):
    """Test handling of voice without authentication."""

    async def async_check_token(*args, **kwargs):
        """Mock token check."""
        raise Unauthenticated("No authentication")

    cloud.auth.async_check_token = async_check_token

    with (
        pytest.raises(
            voice.VoiceError,
            match="No authentication",
        ),
    ):
        await cloud.voice.process_stt(
            stream=b"feet",
            content_type="video=test",
            language="en-US",
        )
