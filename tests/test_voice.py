"""Test for voice functions."""

from datetime import timedelta

import pytest
import xmltodict

from hass_nabucasa import voice


@pytest.fixture
def voice_api(auth_cloud_mock):
    """Voice api fixture."""
    auth_cloud_mock.servicehandlers_server = "test.local"
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
    with pytest.raises(voice.VoiceError):
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


async def test_process_tts_bad_language(voice_api):
    """Test language error handling around tts."""
    with pytest.raises(voice.VoiceError):
        await voice_api.process_tts(
            text="Text for Saying",
            language="en-BAD",
            output=voice.AudioOutput.MP3,
        )


async def test_process_tts_bad_voice(voice_api):
    """Test voice error handling around tts."""
    with pytest.raises(voice.VoiceError):
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

    with pytest.raises(voice.VoiceError):
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

    with pytest.raises(voice.VoiceError):
        await voice_api.process_stt(
            stream=b"feet",
            content_type="video=test",
            language="en-US",
        )

    assert len(aioclient_mock.mock_calls) == 4

    assert "Retrying with new token" in caplog.text
